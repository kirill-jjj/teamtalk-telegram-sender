import logging
from typing import Callable, Dict, Awaitable, TYPE_CHECKING, Any, Set

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, User as AiogramUser

if TYPE_CHECKING:
    # from sender import Application # No longer needed
    from bot.services_container import Services # Import Services

logger = logging.getLogger(__name__)

class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user: AiogramUser | None = data.get("event_from_user")
        # services: "Services" = data["services"] # Get services from workflow_data
        # It's more efficient to get specific cache if that's all that's needed
        subscribed_users_cache: Set[int] = data["subscribed_users_cache"]


        if not user:
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id

        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                # This allows /start <token> for deeplinking, which might be used for initial subscription
                logger.debug(f"SubscriptionCheckMiddleware: Allowing /start command with potential token for user {telegram_id}.")
                return await handler(event, data)

        if telegram_id not in subscribed_users_cache: # Use injected cache
            logger.info(f"SubscriptionCheckMiddleware: Ignored event from non-subscribed user {telegram_id} (Event type: {type(event).__name__}).")
            # Consider sending a message here if desired behavior changes
            # For example:
            # if isinstance(event, Message):
            #     await event.answer("You are not subscribed.")
            # elif isinstance(event, CallbackQuery):
            #     await event.answer("You are not subscribed.", show_alert=True)
            return # Stop processing for non-subscribed users

        logger.debug(f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed. Proceeding (Event type: {type(event).__name__}).")
        return await handler(event, data)
