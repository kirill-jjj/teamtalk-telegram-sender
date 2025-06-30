import asyncio
import sys

from bot.logging_setup import setup_logging
logger = setup_logging()

from aiogram import Bot, Dispatcher, html
from aiogram.types import ErrorEvent, Message
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from pytalk.implementation.TeamTalkPy import TeamTalk5 as sdk

from bot.config import app_config
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.teamtalk_bot import events as tt_events
from bot.database.engine import init_db, SessionFactory
from bot.core.user_settings import load_user_settings_to_cache
from bot.database import crud
from bot.database.crud import get_all_subscribers_ids
from bot.state import SUBSCRIBED_USERS_CACHE, ADMIN_IDS_CACHE
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message
from bot.telegram_bot.commands import set_telegram_commands
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    TeamTalkInstanceMiddleware,
    SubscriptionCheckMiddleware
)
from bot.telegram_bot.handlers import (
    user_commands_router,
    admin_router,
    callback_router,
    catch_all_router
)

try:
    import uvloop
    uvloop.install()
    logger.info("uvloop installed and used.")
except ImportError:
    logger.info("uvloop not found, using default asyncio event loop.")


async def on_startup(bot: Bot, dispatcher: Dispatcher):
    """Executed when the bot starts up."""
    logger.info("Initializing TeamTalk components for on_startup...")
    teamtalk_task = asyncio.create_task(tt_bot_module.tt_bot._start(), name="teamtalk_bot_task_dispatcher")
    dispatcher["teamtalk_task"] = teamtalk_task
    logger.info("TeamTalk task started via on_startup.")

    logger.debug("Fetching admin IDs for Telegram command setup (on_startup)...")
    db_admin_ids = []
    async with SessionFactory() as session:
        db_admin_ids = await crud.get_all_admins_ids(session)
    ADMIN_IDS_CACHE.update(db_admin_ids)
    await set_telegram_commands(bot, admin_ids=db_admin_ids)
    logger.debug("Telegram command setup complete (on_startup).")


async def on_shutdown(dispatcher: Dispatcher):
    """Executed when the bot stops."""
    logger.warning('Stopping bot (on_shutdown)...')

    teamtalk_task = dispatcher.get("teamtalk_task")
    if teamtalk_task and not teamtalk_task.done():
        logger.info("Cancelling TeamTalk task (on_shutdown)...")
        teamtalk_task.cancel()
        try:
            await teamtalk_task
        except asyncio.CancelledError:
            logger.info("TeamTalk task cancelled successfully (on_shutdown).")
        except Exception as e:
            logger.error(f"Error awaiting cancelled TeamTalk task (on_shutdown): {e}", exc_info=True)
    elif teamtalk_task:
        logger.info("TeamTalk task was already done (on_shutdown).")
    else:
        logger.info("No TeamTalk task found in dispatcher context to cancel (on_shutdown).")

    # Close Telegram bot sessions
    if hasattr(tg_bot_event, 'session') and tg_bot_event.session:
        await tg_bot_event.session.close()
    if tg_bot_message and hasattr(tg_bot_message, 'session') and tg_bot_message.session:
        await tg_bot_message.session.close()
    logger.info("Telegram bot sessions closed (on_shutdown).")

    # Disconnect TeamTalk instances (using detailed logic)
    logger.info("Disconnecting TeamTalk instances (on_shutdown)...")
    if tt_bot_module.tt_bot and hasattr(tt_bot_module.tt_bot, 'teamtalks'):
        ttstr = sdk.ttstr
        for tt_instance_item in tt_bot_module.tt_bot.teamtalks:
            try:
                if tt_instance_item.logged_in:
                    tt_instance_item.logout()
                    logger.debug(f"Logged out from TT server: {ttstr(tt_instance_item.server_info.host) if tt_instance_item.server_info else 'Unknown Server'} (on_shutdown)")
                if tt_instance_item.connected:
                    tt_instance_item.disconnect()
                    logger.debug(f"Disconnected from TT server: {ttstr(tt_instance_item.server_info.host) if tt_instance_item.server_info else 'Unknown Server'} (on_shutdown)")
                if hasattr(tt_instance_item, 'closeTeamTalk'):
                    tt_instance_item.closeTeamTalk()
                logger.debug(f"Closed TeamTalk instance for {ttstr(tt_instance_item.server_info.host) if tt_instance_item.server_info else 'Unknown Server'} (on_shutdown)")
            except Exception as e_tt_close:
                logger.error(f"Error closing TeamTalk instance during on_shutdown: {e_tt_close}", exc_info=True)
    else:
        logger.warning("Pytalk bot or 'teamtalks' attribute not found for cleanup during on_shutdown.")
    logger.info("Application shutdown sequence complete (on_shutdown).")


# dp.errors() decorator was removed as dp is defined later in main(); handler registered explicitly.
async def global_error_handler(event: ErrorEvent, bot: Bot):
    """
    Global error handler for uncaught exceptions in handlers.
    """
    # Экранируем текст исключения, чтобы избежать ошибок парсинга HTML
    escaped_exception_text = html.quote(str(event.exception))

    logger.critical(f"Unhandled exception in handler: {event.exception}", exc_info=True)

    if app_config.TG_ADMIN_CHAT_ID:
        try:
            error_text = (
                f"<b>Критическая ошибка!</b>\n"
                f"<b>Тип ошибки:</b> {type(event.exception).__name__}\n"
                f"<b>Сообщение:</b> {escaped_exception_text}" # <-- Используем экранированный текст
            )
            await bot.send_message(app_config.TG_ADMIN_CHAT_ID, error_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Could not send critical error message to admin chat: {e}", exc_info=True)

    user_message = "Произошла непредвиденная ошибка. Администратор уже уведомлен. Пожалуйста, попробуйте позже."
    update = event.update

    try:
        if update.message:
            await update.message.answer(user_message)
        elif update.callback_query and isinstance(update.callback_query.message, Message):
            await update.callback_query.message.answer(user_message)
        # Example of how to acknowledge a callback if message sending fails or is not applicable:
        # elif update.callback_query:
        #     await update.callback_query.answer("Error processed.", show_alert=False) # Generic ack
    except Exception as e:
        logger.error(f"Could not send error message to user: {e}", exc_info=True)


async def main():
    logger.info("Application starting...")

    await init_db()
    async with SessionFactory() as session:
        db_subscriber_ids = await get_all_subscribers_ids(session)
        SUBSCRIBED_USERS_CACHE.update(db_subscriber_ids)
    await load_user_settings_to_cache(SessionFactory)
    await tt_bot_module.tt_bot._async_setup_hook()

    tg_admin_chat_id = app_config.TG_ADMIN_CHAT_ID
    if tg_admin_chat_id is not None:
        async with SessionFactory() as session:
            await crud.add_admin(session, tg_admin_chat_id)

    dp = Dispatcher()

    # Register middlewares
    dp.update.outer_middleware.register(DbSessionMiddleware(SessionFactory))
    dp.message.middleware(SubscriptionCheckMiddleware())
    dp.callback_query.middleware(SubscriptionCheckMiddleware())
    dp.message.middleware(UserSettingsMiddleware())
    dp.callback_query.middleware(UserSettingsMiddleware())
    dp.message.middleware(TeamTalkInstanceMiddleware())
    dp.callback_query.middleware(TeamTalkInstanceMiddleware())
    dp.callback_query.middleware(CallbackAnswerMiddleware())

    # Include routers
    dp.include_router(user_commands_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(catch_all_router)

    # Register startup and shutdown handlers
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Register the global error handler
    dp.errors.register(global_error_handler)

    logger.info("Starting Telegram polling...")
    try:
        await dp.start_polling(tg_bot_event, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Cleanup of resources like DB connections or bot sessions
        # is expected to be handled by the on_shutdown handler.
        logger.info("Application finished.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
    except (ValueError, KeyError) as config_error:
        logger.critical(f"Configuration Error: {config_error}. Please check your .env file or environment variables.")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
