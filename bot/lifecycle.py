"""Application lifecycle handlers."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging

from aiogram import Dispatcher
from dishka.integrations.aiogram import FromDishka, inject
import pytalk

from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.database.engine import AsyncSessionFactoryType
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.event_bus.bus import EventBus
from bot.event_handlers.teamtalk_replier import TeamTalkReplyHandler
from bot.event_handlers.telegram_notifier import TelegramNotificationHandler
from bot.models import Admin
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.events import (
    AdminStatusChangedEvent,
    PrivateMessageReceivedEvent,
    ReplyToTeamTalkUserEvent,
    UserJoinedEvent,
    UserLeftEvent,
)
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter
from bot.telegram_bot.commands import (
    set_telegram_commands as set_telegram_commands_for_bot,
)
from bot.telegram_bot.commands import update_user_bot_commands
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
    event_bus: FromDishka[EventBus],
    telegram_handler: FromDishka[TelegramNotificationHandler],
    teamtalk_replier: FromDishka[TeamTalkReplyHandler],
    admin_repo: FromDishka[AdminRepository],
    subscriber_repo: FromDishka[SubscriberRepository],
    user_repo: FromDishka[UserRepository],
    _tt_event_handler: FromDishka[PytalkEventRouter],
) -> None:
    """Application startup handler."""
    logger = logging.getLogger(__name__)
    logger.info("Application startup...")

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
        admin_repo._session = session
        subscriber_repo._session = session
        user_repo._session = session

        db_admin_ids = await admin_repo.get_all_ids()
        cache.load_admins_from_db(db_admin_ids)

        db_subscriber_ids = await subscriber_repo.get_all_ids()
        cache.load_subscribers_from_db(db_subscriber_ids)

        all_settings = await user_repo.get_all()
        cache.load_all_user_settings(all_settings)
        logger.info("All caches have been loaded.")

        tg_admin_chat_id = settings.telegram.admin_chat_id
        if tg_admin_chat_id and not cache.is_admin(tg_admin_chat_id):
            logger.info(
                "Configured admin %s not found in cache, ensuring presence.",
                tg_admin_chat_id,
            )

            if not await admin_repo.get_by_id(tg_admin_chat_id):
                await admin_repo.add(Admin(telegram_id=tg_admin_chat_id))

            user_settings = await user_repo.get_or_create(
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
        await session.commit()

    logger.info("Setting Telegram bot commands...")
    bot_info = await bot.get_me()
    if bot_info.username:
        cache.set_bot_username(bot_info.username)

    await set_telegram_commands_for_bot(
        bot, cache, translator_factory, available_languages, settings
    )
    logger.info("Telegram bot commands set.")

    logger.info("Subscribing event handlers...")
    event_bus.subscribe(UserJoinedEvent, telegram_handler.handle_user_joined)
    event_bus.subscribe(UserLeftEvent, telegram_handler.handle_user_left)
    event_bus.subscribe(
        PrivateMessageReceivedEvent, telegram_handler.handle_private_message
    )
    event_bus.subscribe(
        AdminStatusChangedEvent, telegram_handler.handle_admin_status_changed
    )
    event_bus.subscribe(ReplyToTeamTalkUserEvent, teamtalk_replier.handle_reply_event)
    logger.info("Event handlers subscribed.")

    logger.info("Final admin count after startup: %s", cache.get_admin_count())
    logger.info("Application startup sequence complete.")
