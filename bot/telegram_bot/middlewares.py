import logging
from typing import Callable, Coroutine, Any, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, User
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import SubscribedUser
from bot.core.user_settings import get_or_create_user_settings, USER_SETTINGS_CACHE
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.language import get_translator


logger = logging.getLogger(__name__)

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: sessionmaker): # type: ignore
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)

class UserSettingsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_obj: User = data["event_from_user"]
        session_obj: AsyncSession = data["session"]

        user_settings = USER_SETTINGS_CACHE.get(user_obj.id)

        if not user_settings:
            user_settings = await get_or_create_user_settings(user_obj.id, session_obj)

        # It's highly unlikely user_settings would still be None here due to get_or_create_user_settings logic,
        # but check defensively.
        if not user_settings:
            logger.error(f"CRITICAL: Could not get or create user settings for user {user_obj.id}")
            # In this case, we can even not call the handler and just exit,
            # to avoid further errors.
            return

        data["user_settings"] = user_settings
        translator = get_translator(user_settings.language)
        data["_"] = translator.gettext
        data["translator"] = translator

        return await handler(event, data)

class TeamTalkInstanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actual_tt_instance = tt_bot_module.current_tt_instance
        data["tt_instance"] = actual_tt_instance
        return await handler(event, data)

class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user") # Aiogram 3.x puts it here

        if not user: # Should not happen if events are from users
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id
        session: AsyncSession | None = data.get("session") # From DbSessionMiddleware

        if not session:
            logger.error("SubscriptionCheckMiddleware: No database session found in event data. Ensure DbSessionMiddleware runs before.")
            # Potentially send an error message or just let it pass to hit an error later
            return await handler(event, data)

        # Allow /start command with a token (deeplink) to pass without subscription check
        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                logger.debug(f"SubscriptionCheckMiddleware: Allowing /start command with token for user {telegram_id}.")
                return await handler(event, data)

        subscriber = await session.get(SubscribedUser, telegram_id)

        if not subscriber:
            logger.info(f"SubscriptionCheckMiddleware: Ignored event from non-subscribed user {telegram_id}.")
            return  # Simply stop processing, do not reply.

        logger.debug(f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed. Proceeding.")
        return await handler(event, data)