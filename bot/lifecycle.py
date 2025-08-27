"""Application lifecycle handlers."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging
import os
from pathlib import Path

from aiogram import Dispatcher
from alembic import command as alembic_command
from alembic.config import Config
from dishka.integrations.aiogram import FromDishka, inject
import pytalk

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.database.engine import AsyncSessionFactoryType
from bot.database.uow import SqlModelUnitOfWork
from bot.event_bus.bus import EventBus
from bot.models import Admin
from bot.registration import register_all_handlers
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter
from bot.telegram_bot.commands import (
    set_telegram_commands as set_telegram_commands_for_bot,
)
from bot.telegram_bot.commands import update_user_bot_commands
from bot.telegram_bot.types.bots import EventBot


def _run_migrations(config_path: str) -> None:
    """Runs database migrations using Alembic."""
    logger = logging.getLogger(__name__)
    logger.info("Checking and applying database migrations...")
    try:
        # Set the environment variable that alembic/env.py uses
        # to ensure Alembic finds the correct config.toml
        os.environ["APP_CONFIG_FILE"] = str(Path(config_path).resolve())

        alembic_cfg = Config("alembic.ini")
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations are up to date.")
    except Exception:
        logger.critical("Failed to apply database migrations.")
        raise
    finally:
        # Clean up the environment variable
        if "APP_CONFIG_FILE" in os.environ:
            del os.environ["APP_CONFIG_FILE"]


@inject
async def on_startup(
    dispatcher: FromDishka[Dispatcher],
    bot: FromDishka[EventBot],
    tt_bot: FromDishka[pytalk.TeamTalkBot],
    cache: FromDishka[CacheService],
    session_factory: FromDishka[AsyncSessionFactoryType],
    settings: FromDishka[Settings],
    translator_factory: FromDishka[Callable[[str], NullTranslations]],
    available_languages: FromDishka[list[LanguageInfo]],
    event_bus: FromDishka[EventBus],
    command_bus: FromDishka[CommandBus],
    config_path: FromDishka[str],
    _tt_event_handler: FromDishka[PytalkEventRouter],
) -> None:
    """Application startup handler."""
    logger = logging.getLogger(__name__)

    try:
        # Run synchronous migration code in a separate thread
        # to avoid blocking the main event loop.
        await asyncio.to_thread(_run_migrations, config_path)
    except Exception:
        logger.critical("Application startup failed due to migration error.")
        # Stop the application if migrations fail
        raise

    logger.info("Application startup...")

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
    async with SqlModelUnitOfWork(session_factory) as uow:
        db_admin_ids = await uow.admins.get_all_ids()
        cache.load_admins_from_db(db_admin_ids)

        db_subscriber_ids = await uow.subscribers.get_all_ids()
        cache.load_subscribers_from_db(db_subscriber_ids)

        all_settings = await uow.users.get_all()
        cache.load_all_user_settings(all_settings)
        logger.info("All caches have been loaded.")

        tg_admin_chat_id = settings.telegram.admin_chat_id
        if tg_admin_chat_id and not cache.is_admin(tg_admin_chat_id):
            logger.info(
                "Configured admin %s not found in cache, ensuring presence.",
                tg_admin_chat_id,
            )

            if not await uow.admins.get_by_id(tg_admin_chat_id):
                await uow.admins.add(Admin(telegram_id=tg_admin_chat_id))

            user_settings = await uow.users.get_or_create(
                tg_admin_chat_id,
                defaults={"language_code": settings.general.default_lang},
            )
            cache.add_admin(tg_admin_chat_id)

            translator = translator_factory(user_settings.language_code)
            await update_user_bot_commands(
                telegram_id=tg_admin_chat_id,
                new_lang_code=user_settings.language_code,
                cache=cache,
                bot=bot,
                translator=translator,
            )

    logger.info("Setting Telegram bot commands...")
    bot_info = await bot.get_me()
    if bot_info.username:
        cache.set_bot_username(bot_info.username)

    await set_telegram_commands_for_bot(
        bot, cache, translator_factory, available_languages, settings
    )
    logger.info("Telegram bot commands set.")

    # Get container from dispatcher to pass to registration function
    container = dispatcher.workflow_data["dishka_container"]
    await register_all_handlers(command_bus, event_bus, container)

    logger.info("Final admin count after startup: %s", cache.get_admin_count())
    logger.info("Application startup sequence complete.")
