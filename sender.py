import asyncio
import logging
import sys

# Setup logging first
from bot.logging_setup import setup_logging
logger = setup_logging() # Setup and get a logger for main

try:
    import uvloop
    uvloop.install()
    logger.info("uvloop installed and used.")
except ImportError:
    logger.info("uvloop not found, using default asyncio event loop.")
    pass

from pytalk.implementation.TeamTalkPy import TeamTalk5 as sdk
ttstr = sdk.ttstr

from aiogram import Dispatcher

from bot.config import app_config # Load config early for potential use
from bot.database.engine import init_db, SessionFactory
from bot.database import crud # Import crud
from bot.core.user_settings import load_user_settings_to_cache
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message
from bot.telegram_bot.commands import set_telegram_commands
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    TeamTalkInstanceMiddleware
)
from bot.telegram_bot.handlers import (
    user_commands_router,
    settings_router,
    admin_router,
    callback_router,
    catch_all_router
)
# Import TeamTalk bot and its events so they are registered
from bot.teamtalk_bot import bot_instance as tt_bot_module
# Ensure TeamTalk events are loaded by importing the events module
from bot.teamtalk_bot import events as tt_events # Loads event handlers

_telegram_polling_task_ref_for_shutdown = None
_teamtalk_task_ref_for_shutdown = None

async def on_aiogram_shutdown(*args, **kwargs):
    logger.info("on_aiogram_shutdown called. Attempting to cancel tasks.")
    global _teamtalk_task_ref_for_shutdown
    if _teamtalk_task_ref_for_shutdown and not _teamtalk_task_ref_for_shutdown.done():
        logger.info("Cancelling TeamTalk task...")
        _teamtalk_task_ref_for_shutdown.cancel()

    global _telegram_polling_task_ref_for_shutdown
    if _telegram_polling_task_ref_for_shutdown and not _telegram_polling_task_ref_for_shutdown.done():
        logger.info("Cancelling Telegram polling task (aiogram should handle this)...")
        _telegram_polling_task_ref_for_shutdown.cancel()

async def main_async():
    logger.info("Application starting...")

    # Initialize database
    await init_db()
    logger.info("Database initialization complete.")

    # Load user settings into cache
    await load_user_settings_to_cache(SessionFactory)
    logger.info("User settings loaded into cache.")

    # Ensure TG_ADMIN_CHAT_ID is in the admin database
    tg_admin_chat_id_str = app_config.get("TG_ADMIN_CHAT_ID")
    if tg_admin_chat_id_str:
        try:
            tg_admin_chat_id = int(tg_admin_chat_id_str)
            logger.info(f"Attempting to ensure TG_ADMIN_CHAT_ID ({tg_admin_chat_id}) is registered as an admin.")
            async with SessionFactory() as session:
                await crud.add_admin(session, tg_admin_chat_id)
            # crud.add_admin handles its own logging for success/failure/already exists
        except ValueError:
            logger.error(f"TG_ADMIN_CHAT_ID '{tg_admin_chat_id_str}' is not a valid integer. Cannot add as admin.")
    else:
        logger.info("TG_ADMIN_CHAT_ID is not set in the configuration. Skipping auto-admin registration.")

    # Fetch all admin IDs from the database to set their commands
    logger.info("Fetching admin IDs from the database for command setup...")
    db_admin_ids = []
    try:
        async with SessionFactory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
        logger.info(f"Fetched {len(db_admin_ids)} admin IDs from the database: {db_admin_ids}")
    except Exception as e:
        logger.error(f"Failed to fetch admin IDs from database: {e}", exc_info=True)
        # Continue with an empty list or handle as critical error depending on desired behavior
        # For now, it will proceed with an empty list if fetching fails.

    # Set Telegram bot commands using admin IDs from the database
    await set_telegram_commands(tg_bot_event, admin_ids=db_admin_ids)
    logger.info("Telegram commands set.")

    # Initialize Aiogram Dispatcher
    # Note: storage can be added here if FSM is used later, e.g., MemoryStorage() or RedisStorage2()
    dp = Dispatcher()

    # Register middlewares
    # Outer middlewares are processed before inner middlewares.
    # DbSessionMiddleware should be early to provide session to others.
    dp.update.outer_middleware.register(DbSessionMiddleware(SessionFactory))
    # TeamTalkInstanceMiddleware provides tt_instance globally.
    dp.update.outer_middleware.register(TeamTalkInstanceMiddleware()) # No args needed

    # UserSettingsMiddleware depends on session, so it's an inner middleware for message/callback_query.
    # It will run after DbSessionMiddleware provides the session.
    dp.message.middleware(UserSettingsMiddleware())
    dp.callback_query.middleware(UserSettingsMiddleware())
    logger.info("Aiogram middlewares registered.")

    # Include routers
    dp.include_router(user_commands_router)
    dp.include_router(settings_router)
    dp.include_router(admin_router) # Admin router includes IsAdminFilter
    dp.include_router(callback_router)
    dp.include_router(catch_all_router) # Catch-all should be last for messages
    logger.info("Aiogram routers included.")

    logger.info("Starting Telegram bot polling and TeamTalk bot...")

    # Pytalk setup hook (if any internal async setup is needed by pytalk)
    # await tt_bot_module.tt_bot._async_setup_hook() # As per original code, if Pytalk requires it.
                                                 # Check Pytalk documentation for current practice.
                                                 # If not needed, this can be removed.
                                                 # Assuming it's for internal Pytalk setup.

    # Start Pytalk bot first (it might take time to connect)
    # The tt_bot.run() or similar method from Pytalk should be used.
    # Original code used tt_bot._start() which implies it's a coroutine.
    # and tt_bot._async_setup_hook()
    # Let's assume Pytalk's start is asyncio compatible.
    # The on_ready event in tt_events will handle the actual server connection.

    dp.shutdown.register(on_aiogram_shutdown)
    telegram_polling_task = dp.start_polling(
        tg_bot_event,
        allowed_updates=dp.resolve_used_update_types() # Optimize updates
    )
    global _telegram_polling_task_ref_for_shutdown
    _telegram_polling_task_ref_for_shutdown = telegram_polling_task
    # Pytalk's start method might be blocking or async.
    # If tt_bot.run() is blocking, it needs its own thread or process.
    # If tt_bot._start() is a coroutine as in original, it can be gathered.
    # The original code had tt_bot._async_setup_hook() then tt_bot._start()
    # This implies _start() is the main loop for pytalk.

    # Pytalk's `add_server` is called in `on_ready`. `tt_bot.connect()` or `tt_bot.run()`
    # is usually the way to start the Pytalk client loop.
    # The original code had `tt_bot._async_setup_hook()` and `tt_bot._start()`.
    # Let's assume `tt_bot_module.tt_bot.run_async()` is the correct modern way if available,
    # or `tt_bot_module.tt_bot.start()` if it's an async method.
    # If Pytalk's main loop is started by `tt_bot.add_server` implicitly or via `on_ready`,
    # then we just need to ensure `on_ready` is triggered.
    # Pytalk's `TeamTalkBot` usually has a `run()` or `start()` method.
    # The original code structure suggests `tt_bot._start()` was the entry point for its event loop.

    # Trigger Pytalk's on_ready to start connection process
    # This will call tt_bot.add_server which then connects.
    # The event loop for Pytalk is managed by Pytalk itself once a server is added and connection starts.
    # We need to ensure Pytalk's internal event processing is running.
    # If Pytalk uses its own thread, this is fine. If it relies on the current asyncio loop,
    # `asyncio.gather` is appropriate.

    # The original `tt_bot._async_setup_hook()` and `tt_bot._start()` suggests Pytalk integrates with asyncio.
    # `_async_setup_hook` is likely for one-time async initializations.
    # `_start` is likely the coroutine that runs Pytalk's event loop.

    await tt_bot_module.tt_bot._async_setup_hook() # Call setup hook as in original
    teamtalk_task = tt_bot_module.tt_bot._start()    # Start Pytalk's async loop
    global _teamtalk_task_ref_for_shutdown
    _teamtalk_task_ref_for_shutdown = teamtalk_task

    try:
        await asyncio.gather(
            telegram_polling_task,
            teamtalk_task
        )
    finally:
        logger.info("Shutting down application...")
        # Gracefully stop polling and close sessions
        await dp.storage.close() # If storage is used
        await dp.fsm.storage.close() # If FSM storage is used

        await tg_bot_event.session.close()
        if tg_bot_message:
            await tg_bot_message.session.close()
        logger.info("Telegram bot sessions closed.")

        # Disconnect TeamTalk instances
        # Pytalk's `teamtalks` attribute holds the list of TeamTalkInstance objects
        logger.info("Disconnecting TeamTalk instances...")
        if tt_bot_module.tt_bot and hasattr(tt_bot_module.tt_bot, 'teamtalks'):
            for tt_instance_item in tt_bot_module.tt_bot.teamtalks:
                try:
                    if tt_instance_item.logged_in:
                        tt_instance_item.logout()
                        logger.info(f"Logged out from TT server: {ttstr(tt_instance_item.server_info.host)}")
                    if tt_instance_item.connected:
                        tt_instance_item.disconnect()
                        logger.info(f"Disconnected from TT server: {ttstr(tt_instance_item.server_info.host)}")
                    # Pytalk might have a method to fully close/cleanup an instance
                    if hasattr(tt_instance_item, 'closeTeamTalk'): # From original code
                        tt_instance_item.closeTeamTalk()
                    logger.info(f"Closed TeamTalk instance for {ttstr(tt_instance_item.server_info.host)}")
                except Exception as e_tt_close:
                    logger.error(f"Error closing TeamTalk instance for {ttstr(tt_instance_item.server_info.host)}: {e_tt_close}")
        else:
            logger.warning("Pytalk bot or 'teamtalks' attribute not found for cleanup.")

        logger.info("Application shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except (ValueError, KeyError) as config_error:
        # Logger might not be fully set up if config fails very early.
        # Print to stderr as a fallback.
        print(f"CRITICAL: Configuration Error: {config_error}. Please check your .env file or environment variables.", file=sys.stderr)
        if logger: # If logger is available, use it.
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
        if logger:
            logger.info("Application finished.")
        else:
            print("Application finished.", file=sys.stderr)
