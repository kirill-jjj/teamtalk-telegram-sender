import asyncio
import sys

from bot.logging_setup import setup_logging
logger = setup_logging()

try:
    import uvloop
    uvloop.install()
    logger.info("uvloop installed and used.")
except ImportError:
    logger.info("uvloop not found, using default asyncio event loop.")

_telegram_polling_task_ref_for_shutdown = None
_teamtalk_task_ref_for_shutdown = None

async def on_aiogram_shutdown(*args, **kwargs):
    logger.info("on_aiogram_shutdown called. Attempting to cancel tasks.")
    global _teamtalk_task_ref_for_shutdown
    if _teamtalk_task_ref_for_shutdown and not _teamtalk_task_ref_for_shutdown.done():
        logger.info("Cancelling TeamTalk task...")
        _teamtalk_task_ref_for_shutdown.cancel()
        try:
            await _teamtalk_task_ref_for_shutdown
        except asyncio.CancelledError:
            logger.info("TeamTalk task cancelled successfully.")
        except Exception as e:
            logger.error(f"Error during TeamTalk task cancellation: {e}", exc_info=True)

    global _telegram_polling_task_ref_for_shutdown
    if _telegram_polling_task_ref_for_shutdown and not _telegram_polling_task_ref_for_shutdown.done():
        logger.info("Requesting cancellation of Telegram polling task...")
        _telegram_polling_task_ref_for_shutdown.cancel()
        try:
            await _telegram_polling_task_ref_for_shutdown
        except asyncio.CancelledError:
            logger.info("Telegram polling task cancelled successfully.")
        except Exception as e:
            logger.error(f"Error awaiting Telegram polling task cancellation: {e}", exc_info=True)


async def main_async():
    logger.info("Application starting...")

    from aiogram import Dispatcher
    from pytalk.implementation.TeamTalkPy import TeamTalk5 as sdk

    from bot.config import app_config
    from bot.teamtalk_bot import bot_instance as tt_bot_module
    from bot.teamtalk_bot import events as tt_events
    from bot.database.engine import init_db, SessionFactory
    from bot.core.user_settings import load_user_settings_to_cache
    from bot.database import crud
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

    ttstr = sdk.ttstr

    logger.debug("Core modules imported. Initializing...")

    logger.info("Initializing TeamTalk components...")
    await init_db()
    logger.info("Database initialization complete.")

    asyncio.create_task(load_user_settings_to_cache(SessionFactory))
    logger.info("User settings cache loading initiated.")

    await tt_bot_module.tt_bot._async_setup_hook()
    teamtalk_task = asyncio.create_task(tt_bot_module.tt_bot._start(), name="teamtalk_bot_task")

    global _teamtalk_task_ref_for_shutdown
    _teamtalk_task_ref_for_shutdown = teamtalk_task
    logger.info("TeamTalk task started.")

    logger.info("Initializing Telegram components...")
    tg_admin_chat_id_str = app_config.get("TG_ADMIN_CHAT_ID")
    if tg_admin_chat_id_str:
        try:
            tg_admin_chat_id = int(tg_admin_chat_id_str)
            logger.debug(f"Ensuring TG_ADMIN_CHAT_ID ({tg_admin_chat_id}) is admin...")
            async with SessionFactory() as session:
                await crud.add_admin(session, tg_admin_chat_id)
        except ValueError:
            logger.error(f"TG_ADMIN_CHAT_ID '{tg_admin_chat_id_str}' is not valid. Cannot add as admin.")
    else:
        logger.info("TG_ADMIN_CHAT_ID not set. Skipping auto-admin registration.")

    logger.debug("Fetching admin IDs for Telegram command setup...")
    db_admin_ids = []
    try:
        async with SessionFactory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
        logger.debug(f"Fetched {len(db_admin_ids)} admin IDs: {db_admin_ids}")
    except Exception as e:
        logger.error(f"Failed to fetch admin IDs: {e}", exc_info=True)

    asyncio.create_task(set_telegram_commands(tg_bot_event, admin_ids=db_admin_ids))
    logger.debug("Telegram command setup initiated.")

    dp = Dispatcher()

    dp.update.outer_middleware.register(DbSessionMiddleware(SessionFactory))
    dp.update.outer_middleware.register(TeamTalkInstanceMiddleware())
    dp.message.middleware(UserSettingsMiddleware())
    dp.callback_query.middleware(UserSettingsMiddleware())
    dp.message.middleware(SubscriptionCheckMiddleware())
    dp.callback_query.middleware(SubscriptionCheckMiddleware())
    logger.debug("Aiogram middlewares registered.")

    dp.include_router(user_commands_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(catch_all_router)
    logger.debug("Aiogram routers included.")

    dp.shutdown.register(on_aiogram_shutdown)

    logger.info("Starting Telegram polling...")
    telegram_polling_task = asyncio.create_task(
        dp.start_polling(
            tg_bot_event,
            allowed_updates=dp.resolve_used_update_types()
        ),
        name="telegram_polling_task"
    )
    global _telegram_polling_task_ref_for_shutdown
    _telegram_polling_task_ref_for_shutdown = telegram_polling_task
    logger.info("Telegram polling task created.")

    logger.info("All components initialized. Awaiting task completion...")
    try:
        await asyncio.gather(
            telegram_polling_task,
            teamtalk_task
        )
    except asyncio.CancelledError:
        logger.info("Main asyncio.gather was cancelled (expected during shutdown).")
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught in main_async gather. Initiating shutdown sequence.")
    finally:
        logger.info("Main gather finished. Proceeding to final cleanup in main_async...")

        if hasattr(dp, 'storage') and hasattr(dp.storage, 'close'):
             await dp.storage.close()
        if hasattr(dp, 'fsm') and hasattr(dp.fsm, 'storage') and hasattr(dp.fsm.storage, 'close'):
             await dp.fsm.storage.close()

        if hasattr(tg_bot_event, 'session') and hasattr(tg_bot_event.session, 'close'):
            await tg_bot_event.session.close()
        if tg_bot_message and hasattr(tg_bot_message, 'session') and hasattr(tg_bot_message.session, 'close'):
            await tg_bot_message.session.close()
        logger.info("Telegram bot sessions closed.")

        logger.info("Disconnecting TeamTalk instances...")
        if tt_bot_module.tt_bot and hasattr(tt_bot_module.tt_bot, 'teamtalks'):
            for tt_instance_item in tt_bot_module.tt_bot.teamtalks:
                try:
                    if tt_instance_item.logged_in:
                        tt_instance_item.logout()
                        logger.debug(f"Logged out from TT server: {ttstr(tt_instance_item.server_info.host) if tt_instance_item.server_info else 'Unknown Server'}")
                    if tt_instance_item.connected:
                        tt_instance_item.disconnect()
                        logger.debug(f"Disconnected from TT server: {ttstr(tt_instance_item.server_info.host) if tt_instance_item.server_info else 'Unknown Server'}")
                    if hasattr(tt_instance_item, 'closeTeamTalk'):
                        tt_instance_item.closeTeamTalk()
                    logger.debug(f"Closed TeamTalk instance for {ttstr(tt_instance_item.server_info.host) if tt_instance_item.server_info else 'Unknown Server'}")
                except Exception as e_tt_close:
                    logger.error(f"Error closing TeamTalk instance: {e_tt_close}", exc_info=True)
        else:
            logger.warning("Pytalk bot or 'teamtalks' attribute not found for cleanup.")
        logger.info("Application shutdown sequence in main_async complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}. Please check your .env file or environment variables.", file=sys.stderr)
        if logger:
            logger.critical(f"Configuration Error: {config_error}. Please check your .env file or environment variables.")
    except KeyboardInterrupt:
        if logger:
            logger.info("Application interrupted by user (KeyboardInterrupt). Shutting down...")
        else:
            print("Application interrupted. Shutting down...", file=sys.stderr)
    except Exception as e_global:
        if logger:
            logger.critical(f"An unexpected critical error occurred in main: {e_global}", exc_info=True)
        else:
            print(f"CRITICAL: Unexpected error: {e_global}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    finally:
        if _telegram_polling_task_ref_for_shutdown and not _telegram_polling_task_ref_for_shutdown.done():
            if logger:
                logger.info("Attempting final cancellation of Telegram polling task from __main__ finally.")
            _telegram_polling_task_ref_for_shutdown.cancel()

        if _teamtalk_task_ref_for_shutdown and not _teamtalk_task_ref_for_shutdown.done():
            if logger:
                logger.info("Attempting final cancellation of TeamTalk task from __main__ finally.")
            _teamtalk_task_ref_for_shutdown.cancel()

        if logger:
            logger.info("Application finished.")
        else:
            print("Application finished.", file=sys.stderr)
