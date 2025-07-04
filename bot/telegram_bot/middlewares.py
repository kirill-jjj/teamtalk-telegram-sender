import logging
from typing import Callable, Coroutine, Any, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, User
from aiogram.exceptions import TelegramAPIError # Import for specific exception handling
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import SubscribedUser # Keep if other middlewares use it, or remove if specific to old sub check
from bot.core.user_settings import get_or_create_user_settings, USER_SETTINGS_CACHE
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.language import get_translator
from bot.state import SUBSCRIBED_USERS_CACHE


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
        translator = get_translator(user_settings.language_code)
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

        # Allow /start command with a token (deeplink) to pass without subscription check
        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                logger.debug(f"SubscriptionCheckMiddleware: Allowing /start command with token for user {telegram_id}.")
                return await handler(event, data)

        if telegram_id not in SUBSCRIBED_USERS_CACHE:
            logger.info(f"SubscriptionCheckMiddleware: Ignored event from non-subscribed user {telegram_id}.")
            return  # Simply stop processing, do not reply.

        logger.debug(f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed (checked via cache). Proceeding.")
        return await handler(event, data)


async def _send_error_response(
    event: TelegramObject,
    text: str,
    show_alert_for_callback: bool = True
) -> None:
    """
    Internal helper to send an error response based on event type.
    """
    if isinstance(event, Message):
        try:
            await event.reply(text)
        except TelegramAPIError as e:
            logger.error(f"TelegramAPIError replying to message in _send_error_response: {e}")
        except Exception as e: # Catch any other unexpected non-API errors
            logger.error(f"Unexpected error replying to message in _send_error_response: {e}", exc_info=True)
    elif isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=show_alert_for_callback)
        except TelegramAPIError as e:
            logger.error(f"TelegramAPIError answering callback query in _send_error_response: {e}")
        except Exception as e: # Catch any other unexpected non-API errors
            logger.error(f"Unexpected error answering callback query in _send_error_response: {e}", exc_info=True)
    else:
        logger.warning(f"_send_error_response: Unhandled event type {type(event)}")


class TeamTalkConnectionMiddleware(BaseMiddleware):
    """
    Checks if the TeamTalk instance is connected and logged in.
    If not, it replies to the user and prevents the handler from executing.
    This middleware should be registered for specific handlers/routers that require
    an active TeamTalk connection.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject, # Can be Message or CallbackQuery
        data: Dict[str, Any],
    ) -> Any:
        tt_instance = data.get("tt_instance")
        translator = data.get("translator") # Assuming UserSettingsMiddleware runs before

        if not translator: # Fallback if UserSettingsMiddleware didn't run or failed
            translator = get_translator() # Default translator

        _ = translator.gettext

        if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
            error_message_text = _("TeamTalk bot is not connected. Please try again later.")

            await _send_error_response(event, error_message_text, show_alert_for_callback=True)

            logger.warning(
                f"TeamTalkConnectionMiddleware: Blocked access for user {data.get('event_from_user', {}).get('id')} "
                f"due to TeamTalk not being connected/logged in. Event type: {type(event).__name__}"
            )
            return None # Stop processing this event

        return await handler(event, data)