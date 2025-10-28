"""Application lifecycle handlers."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Dispatcher
from dishka.integrations.aiogram import FromDishka, inject
import pytalk

if TYPE_CHECKING:
    from dishka import AsyncContainer

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.database.migration import run_migrations
from bot.database.uow import IUnitOfWork
from bot.event_bus.bus import EventBus
from bot.registration import register_all_handlers
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter
from bot.telegram_bot.commands import (
    set_telegram_commands as set_telegram_commands_for_bot,
)
from bot.telegram_bot.types.bots import EventBot


@inject
async def on_startup(
    dispatcher: FromDishka[Dispatcher],
    bot: FromDishka[EventBot],
    tt_bot: FromDishka[pytalk.TeamTalkBot],
    cache: FromDishka[CacheService],
    settings: FromDishka[Settings],
    translator_factory: FromDishka[Callable[[str], NullTranslations]],
    available_languages: FromDishka[list[LanguageInfo]],
    event_bus: FromDishka[EventBus],
    command_bus: FromDishka[CommandBus],
    _tt_event_handler: FromDishka[PytalkEventRouter],
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

    # Start the pytalk event loop in the background
    teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
    if teamtalk_task is None or teamtalk_task.done():
        task_name = "teamtalk_bot_task_dispatcher"
        teamtalk_task = asyncio.create_task(tt_bot._start(), name=task_name)
        dispatcher.workflow_data["teamtalk_task"] = teamtalk_task
        logger.info("Pytalk main event loop task started as '%s'.", task_name)
    else:
        logger.info("Pytalk main event loop task is already running.")

    logger.info("Loading all caches from database...")
    container: AsyncContainer = dispatcher.workflow_data["dishka_container"]
    async with container() as request_container:
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
    container = dispatcher.workflow_data["dishka_container"]
    await register_all_handlers(command_bus, event_bus, container)

    logger.debug("Final admin count after startup: %s", cache.get_admin_count())
    logger.debug("Application startup sequence complete.")
