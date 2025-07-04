import logging
from typing import Callable, Coroutine, Any, Dict, Awaitable, TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, User as AiogramUser # Renamed User to AiogramUser
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.orm import sessionmaker # Kept for DbSessionMiddleware type hint
from sqlalchemy.ext.asyncio import AsyncSession

# from bot.core.user_settings import get_or_create_user_settings, USER_SETTINGS_CACHE # Removed this import
# Removed: from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.language import get_translator
# Removed: from bot.state import SUBSCRIBED_USERS_CACHE
# Import TeamTalkConnection for type hinting
from bot.teamtalk_bot.connection import TeamTalkConnection


if TYPE_CHECKING:
    from sender import Application # Import Application for type hinting

logger = logging.getLogger(__name__)

# --- Helper function (can be moved to a utils module if preferred) ---
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
        except Exception as e:
            logger.error(f"Unexpected error replying to message in _send_error_response: {e}", exc_info=True)
    elif isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=show_alert_for_callback)
        except TelegramAPIError as e:
            logger.error(f"TelegramAPIError answering callback query in _send_error_response: {e}")
        except Exception as e:
            logger.error(f"Unexpected error answering callback query in _send_error_response: {e}", exc_info=True)
    else:
        logger.warning(f"_send_error_response: Unhandled event type {type(event)}")


# --- Existing Middlewares (some adapted) ---

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
        user_obj: AiogramUser = data["event_from_user"]
        session_obj: AsyncSession = data["session"]
        app: "Application" = data["app"] # <-- Получаем наш главный класс из data

        # Получаем настройки из кэша, который теперь является атрибутом app
        user_settings = app.user_settings_cache.get(user_obj.id)

        if not user_settings:
            # Вызываем метод get_or_create_user_settings из app
            user_settings = await app.get_or_create_user_settings(user_obj.id, session_obj)

        if not user_settings: # This check is fine, get_or_create_user_settings might return None on DB error
            logger.error(f"CRITICAL: Could not get or create user settings for user {user_obj.id}")
            return

        data["user_settings"] = user_settings
        translator = get_translator(user_settings.language_code)
        data["_"] = translator.gettext
        data["translator"] = translator

        return await handler(event, data)

class SubscriptionCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user: AiogramUser | None = data.get("event_from_user")
        app: "Application" = data["app"] # Expect ApplicationMiddleware to provide this

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
            logger.info(f"SubscriptionCheckMiddleware: Ignored event from non-subscribed user {telegram_id}.")
            # Consider sending a message here if desired behavior changes
            return

        logger.debug(f"SubscriptionCheckMiddleware: User {telegram_id} is subscribed. Proceeding.")
        return await handler(event, data)


# --- New/Refactored Middlewares for Application and TeamTalkConnection ---

class ApplicationMiddleware(BaseMiddleware):
    """
    Injects the Application instance into the data of each event.
    """
    def __init__(self, app_instance: "Application"):
        super().__init__()
        self.app_instance = app_instance

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["app"] = self.app_instance
        return await handler(event, data)


class ActiveTeamTalkConnectionMiddleware(BaseMiddleware):
    """
    Injects an active TeamTalkConnection instance into the event data.
    For now, assumes a single primary connection if multiple exist.
    This replaces the old TeamTalkInstanceMiddleware.
    """
    def __init__(self, default_server_key: str | None = None):
        super().__init__()
        self.default_server_key = default_server_key # Optional: key for a default server if multiple

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        app: "Application" = data["app"] # Expect ApplicationMiddleware to run first

        determined_connection: TeamTalkConnection | None = None

        if not app.connections:
            logger.warning("ActiveTeamTalkConnectionMiddleware: No TeamTalk connections available in Application.")
            data["tt_connection"] = None
            return await handler(event, data)

        if self.default_server_key and self.default_server_key in app.connections:
            determined_connection = app.connections[self.default_server_key]
        elif app.connections:
            # Fallback: use the first available connection if no default key or default not found
            # This is suitable for single-server setups or simple multi-server without specific routing yet
            determined_connection = next(iter(app.connections.values()))
            if self.default_server_key: # Log if default was specified but not found
                 logger.warning(f"ActiveTeamTalkConnectionMiddleware: Default server key '{self.default_server_key}' not found. Falling back to first available connection.")
            else:
                 logger.debug(f"ActiveTeamTalkConnectionMiddleware: Using first available connection for {determined_connection.server_info.host if determined_connection else 'N/A'}.")

        if determined_connection:
            logger.debug(f"ActiveTeamTalkConnectionMiddleware: Providing connection for {determined_connection.server_info.host} to handler.")
        else:
            logger.warning("ActiveTeamTalkConnectionMiddleware: Could not determine a TeamTalk connection to provide.")

        data["tt_connection"] = determined_connection
        return await handler(event, data)


class TeamTalkConnectionCheckMiddleware(BaseMiddleware): # Renamed from TeamTalkConnectionMiddleware to avoid confusion
    """
    Checks if the provided TeamTalkConnection (from ActiveTeamTalkConnectionMiddleware)
    is connected and logged in (ready for use).
    If not, it replies to the user and prevents the handler from executing.
    This middleware should be registered for specific handlers/routers that require
    an active and ready TeamTalk connection.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # tt_instance = data.get("tt_instance") # Old way
        tt_connection: TeamTalkConnection | None = data.get("tt_connection")
        translator = data.get("translator") # Assuming UserSettingsMiddleware runs before

        if not translator:
            translator = get_translator()
        _ = translator.gettext

        # Check if a connection object was provided at all
        if not tt_connection:
            error_message_text = _("TeamTalk service is currently unavailable. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            logger.warning(
                f"TeamTalkConnectionCheckMiddleware: Blocked access for user {data.get('event_from_user', {}).get('id')} "
                f"because no TeamTalkConnection object was found in context. Event type: {type(event).__name__}"
            )
            return None

        # Check if the provided connection is ready (connected & logged in & finalized)
        if not tt_connection.is_ready or not tt_connection.is_finalized:
            error_message_text = _("TeamTalk bot is not connected or not fully initialized. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            logger.warning(
                f"TeamTalkConnectionCheckMiddleware: Blocked access for user {data.get('event_from_user', {}).get('id')} "
                f"for server {tt_connection.server_info.host} due to TeamTalk not being ready "
                f"(connected: {tt_connection.instance.connected if tt_connection.instance else 'N/A'}, "
                f"logged_in: {tt_connection.instance.logged_in if tt_connection.instance else 'N/A'}, "
                f"finalized: {tt_connection.is_finalized}). Event type: {type(event).__name__}"
            )
            return None

        logger.debug(f"TeamTalkConnectionCheckMiddleware: Access granted for server {tt_connection.server_info.host}. Connection is ready.")
        return await handler(event, data)