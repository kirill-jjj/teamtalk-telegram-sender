from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.types import User as AiogramUser

if TYPE_CHECKING:
    # from sender import Application # No longer needed
    pass  # Import Services

logger = logging.getLogger(__name__)


class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user: AiogramUser | None = data.get("event_from_user")
        # services: "Services" = data["services"] # Get services from workflow_data
        # It's more efficient to get specific cache if that's all that's needed
        subscribed_users_cache: set[int] = data["subscribed_users_cache"]

        if not user:
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id

        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                # This allows /start <token> for deeplinking, which might be used for initial subscription
                logger.debug(
                    f"SubscriptionCheckMiddleware: Allowing /start command with potential token for user {telegram_id}."
                )
                return await handler(event, data)

        if telegram_id not in subscribed_users_cache:  # Use injected cache
            logger.info(
                f"SubscriptionCheckMiddleware: Ignored event from non-subscribed user {telegram_id} "
                f"(Event type: {type(event).__name__})."
            )
            # Consider sending a message here if desired behavior changes
            # For example:
            # if isinstance(event, Message):
            #     await event.answer("You are not subscribed.")
            # elif isinstance(event, CallbackQuery):
            #     await event.answer("You are not subscribed.", show_alert=True)
            return  # Stop processing for non-subscribed users

        logger.debug(
            f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed. "
            f"Proceeding (Event type: {type(event).__name__})."
        )
        return await handler(event, data)
