import logging
from typing import Callable, Coroutine, Any, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, User
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk # For TeamTalkInstance type hint
from bot.core.user_settings import (
    UserSpecificSettings,
    get_or_create_user_settings
)
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.language import get_translator
from bot.database.models import SubscribedUser


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
        user_obj = data.get("event_from_user")
        session_obj: AsyncSession | None = data.get("session")

        if user_obj and session_obj:
            user_specific_settings = await get_or_create_user_settings(user_obj.id, session_obj)
        else:
            user_specific_settings = UserSpecificSettings()
            logger.warning(f"UserSettingsMiddleware: No user or session. Using default settings.")

        translator = get_translator(user_specific_settings.language)
        data["_"] = translator.gettext
        data["translator"] = translator

        data["user_specific_settings"] = user_specific_settings

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

# --- SubscriptionCheckMiddleware Class Definition ---
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

        # Retrieve the translator function, with a fallback
        temp_translator_func = data.get("_")
        if temp_translator_func is None:
            logger.warning("SubscriptionCheckMiddleware: Translator '_' not found in data. Using default English translator for this message.")
            temp_translator_func = get_translator("en").gettext
        _ = temp_translator_func

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
            logger.info(f"SubscriptionCheckMiddleware: User {telegram_id} is not subscribed. Blocking further processing.")
            # English source for PLEASE_SUBSCRIBE_FIRST: "You are not subscribed. Please go to the TeamTalk server, send the /sub command to the bot in a private message, and click the link you receive to subscribe."
            message_text = _("You are not subscribed. Please go to the TeamTalk server, send the /sub command to the bot in a private message, and click the link you receive to subscribe.")
            try:
                if isinstance(event, Message):
                    await event.reply(message_text)
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(message_text) # Send as new message in chat
                    await event.answer() # Close the callback query notification
            except Exception as e:
                logger.error(f"SubscriptionCheckMiddleware: Error sending 'please subscribe' message to {telegram_id}: {e}")
            return # Stop processing this event further

        logger.debug(f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed. Proceeding.")
        return await handler(event, data)