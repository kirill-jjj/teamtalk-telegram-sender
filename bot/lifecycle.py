"""Application lifecycle handlers."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Dispatcher
from dishka.integrations.aiogram import FromDishka, inject
from pytalk.bot import TeamTalkBot

if TYPE_CHECKING:
    from dishka import AsyncContainer

from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.database.migration import run_migrations
from bot.database.uow import IUnitOfWork
from bot.event_bus.bus import EventBus
from bot.registration import register_all_handlers
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter
from bot.telegram_bot.commands import (
    set_telegram_commands as set_telegram_commands_for_bot,
)
from bot.telegram_bot.types.bots import EventBot


async def deeplink_cleanup_task(
    app_container: "AsyncContainer",
    settings: "Settings",
) -> None:
    """A background task that periodically cleans up expired deeplinks."""
    logger = logging.getLogger(__name__)
    logger.info("Starting periodic deeplink cleanup task.")
    interval = settings.operational_parameters.deeplink_cleanup_interval_seconds
    while True:
        await asyncio.sleep(interval)
        logger.info("Running deeplink cleanup...")
        try:
            async with app_container() as request_container:
                uow = await request_container.get(IUnitOfWork)
                deeplink_service = await request_container.get(DeeplinkService)
                async with uow:
                    deleted_count = await deeplink_service.cleanup_expired_deeplinks(
                        uow
                    )

                if deleted_count > 0:
                    logger.info("Cleaned up %d expired deeplinks.", deleted_count)
                else:
                    logger.debug("No expired deeplinks to clean up.")
        except Exception:
            logger.exception("Error during periodic deeplink cleanup.")


@inject
async def on_startup(
    dispatcher: FromDishka[Dispatcher],
    bot: FromDishka[EventBot],
    tt_bot: FromDishka[TeamTalkBot],
    cache: FromDishka[CacheService],
    settings: FromDishka[Settings],
    translator_factory: FromDishka[Callable[[str], NullTranslations]],
    available_languages: FromDishka[list[LanguageInfo]],
    event_bus: FromDishka[EventBus],
) -> None:
    """Application startup handler."""
    logger = logging.getLogger(__name__)

    logger.debug("Application startup...")

    # Define project root relative to the current file
    project_root = await asyncio.to_thread(
        lambda: Path(__file__).resolve().parent.parent  # noqa: ASYNC240
    )
    # Run migrations before doing anything with the database
    await run_migrations(settings, project_root)

    app_container: AsyncContainer = dispatcher.workflow_data["dishka_container"]

    # Start the pytalk event loop in the background
    teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
    if teamtalk_task is None or teamtalk_task.done():
        task_name = "teamtalk_bot_task_dispatcher"
        teamtalk_task = asyncio.create_task(tt_bot._start(), name=task_name)
        dispatcher.workflow_data["teamtalk_task"] = teamtalk_task
        logger.info("Pytalk main event loop task started as '%s'.", task_name)
    else:
        logger.info("Pytalk main event loop task is already running.")

    # Start the deeplink cleanup task
    cleanup_task = dispatcher.workflow_data.get("deeplink_cleanup_task")
    if cleanup_task is None or cleanup_task.done():
        task_name = "deeplink_cleanup_task"
        cleanup_task = asyncio.create_task(
            deeplink_cleanup_task(app_container, settings), name=task_name
        )
        dispatcher.workflow_data["deeplink_cleanup_task"] = cleanup_task
        logger.info("Deeplink cleanup task started as '%s'.", task_name)
    else:
        logger.info("Deeplink cleanup task is already running.")

    # Explicitly get PytalkEventRouter to ensure its handlers are registered
    await app_container.get(PytalkEventRouter)

    tt_connection = await app_container.get(TeamTalkConnection)
    if not tt_connection.is_ready:
        logger.error("TeamTalk connection is not ready after startup.")

    logger.info("Loading all caches from database...")
    async with app_container() as request_container:
        uow = await request_container.get(IUnitOfWork)
        async with uow:
            db_admin_ids = await uow.admins.get_all_ids()
            cache.load_admins_from_db(db_admin_ids)

            db_subscriber_ids = await uow.subscribers.get_all_ids()
            cache.load_subscribers_from_db(db_subscriber_ids)

            all_settings = await uow.users.get_all()
            cache.load_all_user_settings(all_settings)
            logger.debug("All caches have been loaded.")

        admin_service = await request_container.get(AdminService)
        # Ensure the main admin from config exists and has up-to-date commands
        async with uow:
            await admin_service.ensure_main_admin_exists(uow, bot, translator_factory)

    logger.info("Setting Telegram bot commands...")
    bot_info = await bot.get_me()
    if bot_info.username:
        cache.set_bot_username(bot_info.username)

    await set_telegram_commands_for_bot(
        bot, cache, translator_factory, available_languages, settings
    )
    logger.debug("Telegram bot commands set.")

    # Get container from dispatcher to pass to registration function
    await register_all_handlers(event_bus, app_container)

    logger.debug("Final admin count after startup: %s", cache.get_admin_count())
    logger.debug("Application startup sequence complete.")
