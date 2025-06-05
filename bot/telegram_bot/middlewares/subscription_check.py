import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, User
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import SubscribedUser
from bot.localization import get_text

logger = logging.getLogger(__name__)

class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        # Try to get user object from event
        user: User | None = data.get("event_from_user") # Aiogram 3.x puts it here

        if not user: # Should not happen if events are from users
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id
        session: AsyncSession | None = data.get("session") # From DbSessionMiddleware
        language: str = data.get("language", "en") # From UserSettingsMiddleware (or default)

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

        # Check subscription status
        subscriber = await session.get(SubscribedUser, telegram_id)

        if not subscriber:
            logger.info(f"SubscriptionCheckMiddleware: User {telegram_id} is not subscribed. Blocking further processing.")
            message_text = get_text("PLEASE_SUBSCRIBE_FIRST", language)
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
