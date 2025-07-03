import asyncio
import os
import argparse
import traceback # For detailed error reporting before logger is set up

# === CONFIGURATION BLOCK START ===
# This block must come BEFORE imports from your application.
def main():
    # We define the parser inside main so it doesn't run on import,
    # but parsing logic is called before anything else.
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default=".env",
        help="Path to the configuration file (e.g., .env, prod.env). Defaults to '.env'",
    )
    args, _ = parser.parse_known_args()

    # Set the environment variable that bot.config will read
    os.environ["APP_CONFIG_FILE_PATH"] = args.config

    # Now that the environment variable is set, we can safely
    # run the main asynchronous code, which will import app_config.
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped!")
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}. Please check your .env file or environment variables.")
    except Exception as e:
        print(f"CRITICAL: An unexpected critical error occurred: {e}")
        # For debugging, traceback can also be printed
        traceback.print_exc()

async def async_main():
    # Now we import everything else here, AFTER setting the env var
    from bot.logging_setup import setup_logging
    logger = setup_logging()

    # Imports that depend on configuration
    from aiogram import Bot, Dispatcher, html
    from aiogram.types import ErrorEvent, Message
    from aiogram.utils.callback_answer import CallbackAnswerMiddleware
    from pytalk.implementation.TeamTalkPy import TeamTalk5 as sdk
    import pytalk.exceptions # Added for specific exception handling

    from bot.config import app_config # <--- Config is imported here
    from bot.teamtalk_bot import bot_instance as tt_bot_module
    from bot.teamtalk_bot import events as tt_events  # noqa: F401 # DO NOT REMOVE: Critical for TeamTalk event registration
    from bot.database.engine import SessionFactory
    from bot.core.user_settings import load_user_settings_to_cache
    from bot.database import crud
    from bot.database.crud import get_all_subscribers_ids
    from bot.state import SUBSCRIBED_USERS_CACHE, ADMIN_IDS_CACHE
    from bot.core.languages import discover_languages, AVAILABLE_LANGUAGES_DATA # Import discovery components
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
        # menu_callback_router will be imported separately to avoid circular if it grows
    )
    from bot.telegram_bot.handlers.menu_callbacks import menu_callback_router # Import the new router
    from bot.telegram_bot.handlers.callback_handlers.subscriber_actions import subscriber_actions_router # Import new subscriber actions router

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
            ttstr = sdk.ttstr # Define ttstr here if sdk is only imported in async_main
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
                except (pytalk.exceptions.TeamTalkException, TimeoutError, ConnectionError, OSError) as e_tt_close:
                    logger.error(f"Error closing TeamTalk instance during on_shutdown: {e_tt_close}", exc_info=True)
                # Deliberately not catching generic Exception here to allow critical shutdown errors to propagate
        else:
            logger.warning("Pytalk bot or 'teamtalks' attribute not found for cleanup during on_shutdown.")
        logger.info("Application shutdown sequence complete (on_shutdown).")


    async def global_error_handler(event: ErrorEvent, bot: Bot):
        """
        Global error handler for uncaught exceptions in handlers.
        """
        # Escape the exception text to avoid HTML parsing errors
        escaped_exception_text = html.quote(str(event.exception))

        logger.critical(f"Unhandled exception in handler: {event.exception}", exc_info=True)

        if app_config.TG_ADMIN_CHAT_ID:
            try:
                error_text = (
                    f"<b>Критическая ошибка!</b>\n"
                    f"<b>Тип ошибки:</b> {type(event.exception).__name__}\n"
                    f"<b>Сообщение:</b> {escaped_exception_text}" # <-- Use the escaped text
                )
                await bot.send_message(app_config.TG_ADMIN_CHAT_ID, error_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Could not send critical error message to admin chat: {e}", exc_info=True)

        user_message = "Произошла непредвиденная ошибка. Администратор уже уведомлен. Пожалуйста, попробуйте позже."
        update = event.update

        user_id = None
        if update.message and update.message.from_user:
            user_id = update.message.from_user.id
        elif update.callback_query and update.callback_query.from_user:
            user_id = update.callback_query.from_user.id

        # Check if the user who caused the error is the admin
        # We need app_config here. It's imported earlier in async_main.
        if user_id and app_config.TG_ADMIN_CHAT_ID and user_id == app_config.TG_ADMIN_CHAT_ID:
            logger.debug("Error originated from admin user. Suppressing generic error message to admin.")
        else:
            try:
                if update.message:
                    await update.message.answer(user_message)
                elif update.callback_query and isinstance(update.callback_query.message, Message):
                    await update.callback_query.message.answer(user_message)
            except Exception as e:
                logger.error(f"Could not send error message to user: {e}", exc_info=True)

    logger.info("Application starting...")

    # --- Initialize Languages ---
    logger.info("Discovering available languages...")
    discovered_langs = discover_languages()
    AVAILABLE_LANGUAGES_DATA.extend(discovered_langs) # Populate the global list
    if not AVAILABLE_LANGUAGES_DATA:
        logger.critical("No languages discovered (not even default). Check locales setup.")
        # Potentially exit if no languages can be loaded.
    else:
        logger.info(f"Available languages loaded: {[lang['code'] for lang in AVAILABLE_LANGUAGES_DATA]}")
    # --- End Initialize Languages ---

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
    # callback_router likely contains general callbacks, subscriber_list_router for pagination/old delete
    # and subscriber_actions_router for new detailed actions. Order might matter if filters overlap.
    # For now, adding it along with others.
    dp.include_router(callback_router)
    dp.include_router(menu_callback_router)
    dp.include_router(subscriber_actions_router) # Added subscriber_actions_router
    dp.include_router(catch_all_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.errors.register(global_error_handler)

    logger.info("Starting Telegram polling...")
    try:
        await dp.start_polling(tg_bot_event, allowed_updates=dp.resolve_used_update_types())
    finally:
        logger.info("Application finished.")


if __name__ == "__main__":
    main()
