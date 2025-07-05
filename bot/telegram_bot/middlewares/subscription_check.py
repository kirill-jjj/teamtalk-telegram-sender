import logging
from typing import Callable, Dict, Awaitable, TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, User as AiogramUser

if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)

class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user: AiogramUser | None = data.get("event_from_user")
        app: "Application" = data["app"]

        if not user:
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id

        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                logger.debug(f"SubscriptionCheckMiddleware: Allowing /start command with token for user {telegram_id}.")
                return await handler(event, data)

        if telegram_id not in app.subscribed_users_cache: # Use app's cache
            logger.info(f"SubscriptionCheckMiddleware: Ignored event from non-subscribed user {telegram_id} (Event type: {type(event).__name__}).")
            # Consider sending a message here if desired behavior changes
            return

        logger.debug(f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed. Proceeding (Event type: {type(event).__name__}).")
        return await handler(event, data)
