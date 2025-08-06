"""Application lifecycle handlers."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging

from aiogram import Dispatcher
from dishka.integrations.aiogram import FromDishka, inject
import pytalk
from sqlalchemy.orm import selectinload
from sqlmodel import select

from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.database import crud
from bot.database.engine import AsyncSessionFactoryType
from bot.models import UserSettings
from bot.services import admin_service
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
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
    session_factory: FromDishka[AsyncSessionFactoryType],
    settings: FromDishka[Settings],
    translator_factory: FromDishka[Callable[[str], NullTranslations]],
    available_languages: FromDishka[list[LanguageInfo]],
    _tt_event_handler: FromDishka[TeamTalkEventHandler],
) -> None:
    """Application startup handler."""
    logger = logging.getLogger(__name__)
    logger.info("Application startup...")

    # The TeamTalkEventHandler is now managed by dishka.
    # Simply requesting it (`_tt_event_handler`) is enough to initialize it.
    teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
    if teamtalk_task is None or teamtalk_task.done():
        await tt_bot._async_setup_hook()
        task_name = "teamtalk_bot_task_dispatcher"
        teamtalk_task = asyncio.create_task(tt_bot._start(), name=task_name)
        dispatcher.workflow_data["teamtalk_task"] = teamtalk_task
        logger.info("Pytalk main event loop task started as '%s'.", task_name)
    else:
        logger.info("Pytalk main event loop task is already running.")

    logger.info("Loading all caches from database...")
    async with session_factory() as session:
        db_admin_ids = await crud.get_all_admins_ids(session)
        cache.load_admins_from_db(db_admin_ids)
        db_subscriber_ids = await crud.get_all_subscribers_ids(session)
        cache.load_subscribers_from_db(db_subscriber_ids)
        all_settings_result = await session.execute(
            select(UserSettings).options(
                selectinload(UserSettings.muted_users_list)  # type: ignore[arg-type]
            )
        )
        cache.load_all_user_settings(list(all_settings_result.scalars().all()))
        logger.info("All caches have been loaded.")

        tg_admin_chat_id = settings.telegram.admin_chat_id
        if tg_admin_chat_id and not cache.is_admin(tg_admin_chat_id):
            logger.info(
                "Configured admin %s not found in cache, ensuring presence.",
                tg_admin_chat_id,
            )
            user_settings = await session.get(UserSettings, tg_admin_chat_id)
            if not user_settings:
                user_settings = UserSettings(
                    telegram_id=tg_admin_chat_id,
                    language_code=settings.general.default_lang,
                )
                session.add(user_settings)
                await session.commit()
                await session.refresh(user_settings)
            translator = translator_factory(user_settings.language_code)
            await admin_service.add_admin(session, tg_admin_chat_id, user_settings, cache, bot, translator)

    logger.info("Setting Telegram bot commands...")
    await set_telegram_commands_for_bot(bot, cache, translator_factory, available_languages, settings)
    logger.info("Telegram bot commands set.")

    logger.info("Final admin count after startup: %s", cache.get_admin_count())
    logger.info("Application startup sequence complete.")
