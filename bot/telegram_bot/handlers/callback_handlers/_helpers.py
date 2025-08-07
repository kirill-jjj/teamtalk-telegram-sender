from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any, Protocol, TypeAlias, TypeVar, cast

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from bot.database.repositories.user_repository import UserRepository
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberCallback,
)
from bot.telegram_bot.keyboards import create_subscriber_action_menu_keyboard
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import safe_edit_text
from bot.telegram_bot.utils import format_telegram_user_display_name

logger = logging.getLogger(__name__)

__all__ = [
    "_display_subscriber_view",
    "ensure_message_context",
    "ensure_tt_user_exists",
    "refresh_subscriber_view",
    "safe_edit_text",
    "with_view_refresh",
]

RefreshableViewCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberNotificationPrefCallback
    | AdminSetSubscriberMuteModeCallback
    | SubscriberCallback
)


ViewRefresher: TypeAlias = Callable[..., Awaitable[None]]


def with_view_refresh(
    view_refresher: ViewRefresher,
) -> Callable[
    [Callable[..., Awaitable[tuple[bool, str, Any | None]]]],
    Callable[..., Awaitable[None]],
]:
    """Decorator factory for actions that result in refreshing a view.

    The decorated function MUST return a tuple: (success, message, updated_object).
    """

    def decorator(
        func: Callable[..., Awaitable[tuple[bool, str, Any | None]]],
    ) -> Callable[..., Awaitable[None]]:
        @functools.wraps(func)
        async def wrapper(
            **kwargs: Any,  # noqa: ANN401
        ) -> None:
            """Wrapper function for the with_view_refresh decorator."""
            query = kwargs.pop("query")
            callback_answer = kwargs.pop("callback_answer")

            success, message, updated_object = await func(**kwargs)

            callback_answer.text = message
            callback_answer.show_alert = not success

            if updated_object and isinstance(updated_object, UserSettings):
                kwargs["user_settings"] = updated_object

            await view_refresher(
                query=query,
                **kwargs,
            )

        return wrapper

    return decorator


async def refresh_subscriber_view(
    query: CallbackQuery,
    callback_data: RefreshableViewCallback,
    translator: NullTranslations,
    bot: "EventBot",
    user_repo: UserRepository,
    **kwargs: object,
) -> None:
    """Refresher function for the subscriber detail view."""
    target_telegram_id = callback_data.target_telegram_id
    page_context = getattr(
        callback_data, "subscriber_page_context", getattr(callback_data, "page", 0)
    )

    user_settings = await user_repo.get_by_id(target_telegram_id)
    if not user_settings:
        await query.answer("User not found.", show_alert=True)
        return

    await _display_subscriber_view(
        query=query,
        target_telegram_id=target_telegram_id,
        page_context=page_context,
        user_settings=user_settings,
        translator=translator,
        bot=bot,
    )


def ensure_message_context(
    func: Callable[..., Awaitable[Any | None]],
) -> Callable[..., Awaitable[Any | None]]:
    """Decorator to ensure that a callback query handler has a message context."""

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,
        translator: NullTranslations,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        _ = translator.gettext
        error_message_for_missing_context = _("Error processing command.")

        if not query.message:
            logger.error(
                "Handler '%s': query.message is None. Callback data: %s. User ID: %s",
                func.__name__,
                query.data,
                query.from_user.id,
            )
            try:
                await query.answer(error_message_for_missing_context, show_alert=True)
            except TelegramAPIError:
                logger.exception(
                    "Failed to answer callback query in decorator for '%s'.",
                    func.__name__,
                )
            return

        await func(query, *args, translator=translator, **kwargs)

    return wrapper


def ensure_tt_user_exists(
    func: Callable[..., Awaitable[Any | None]],
) -> Callable[..., Awaitable[Any | None]]:
    """Decorator to ensure that a TeamTalk user from a callback query exists."""

    class CallbackWithUserId(Protocol):
        user_id: int

    T = TypeVar("T", bound=CallbackWithUserId)

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,
        callback_data: T,
        translator: NullTranslations,
        tt_connection: TeamTalkConnection,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        _ = translator.gettext
        if not hasattr(callback_data, "user_id"):
            logger.error(
                "Handler '%s': could not find callback_data with user_id.",
                func.__name__,
            )
            await query.answer(
                _("Error processing command: Invalid callback data."), show_alert=True
            )
            return

        if not tt_connection.instance:
            logger.error("Handler '%s': tt_connection has no instance.", func.__name__)
            await query.answer(
                _("Error: No active TeamTalk connection."), show_alert=True
            )
            return

        server_host = tt_connection.server_info.host
        user_to_act_on = tt_connection.instance.get_user(callback_data.user_id)

        if not user_to_act_on:
            await query.answer(
                _("User not found on server {server_host} anymore.").format(
                    server_host=server_host
                ),
                show_alert=True,
            )
            try:
                await cast(Message, query.message).edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                logger.debug(
                    "Failed to remove reply markup when user %s was not found on %s.",
                    callback_data.user_id,
                    server_host,
                )
            return

        kwargs["tt_user"] = user_to_act_on
        await func(
            query,
            callback_data,
            *args,
            translator=translator,
            tt_connection=tt_connection,
            **kwargs,
        )

    return wrapper


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    user_settings: UserSettings,
    translator: NullTranslations,
    bot: "EventBot",
) -> None:
    """Helper function to display the subscriber details view."""
    _ = translator.gettext

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    display_name = str(target_telegram_id)

    try:
        chat_info = await bot.get_chat(user_settings.telegram_id)
        display_name = format_telegram_user_display_name(chat_info)
    except TelegramAPIError:
        logger.exception(
            "Could not fetch chat info for %s via Telegram API.",
            user_settings.telegram_id,
        )
    except Exception:
        logger.exception(
            "Unexpected error fetching chat info for %s.", user_settings.telegram_id
        )

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    details_parts.append(
        _("Linked TT Account: {tt_username}").format(
            tt_username=user_settings.teamtalk_username or _("None")
        )
    )
    details_parts.append(_("Language: {lang}").format(lang=user_settings.language_code))
    noon_status = _("Enabled") if user_settings.not_on_online_enabled else _("Disabled")
    details_parts.append(_("NOON (Not on Online): {status}").format(status=noon_status))
    notif_setting_map = {
        NotificationSetting.ALL.value: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF.value: _("Join Only"),
        NotificationSetting.JOIN_OFF.value: _("Leave Only"),
        NotificationSetting.NONE.value: _("None"),
    }
    notif_setting_str = user_settings.notification_settings.value
    details_parts.append(
        _("Notifications: {setting}").format(
            setting=notif_setting_map.get(notif_setting_str, notif_setting_str)
        )
    )
    mute_mode_str = (
        _("Blacklist")
        if user_settings.mute_list_mode == MuteListMode.blacklist
        else _("Whitelist")
    )
    details_parts.append(_("Mute Mode: {mode}").format(mode=mute_mode_str))

    text = "\n".join(details_parts)
    # This assumes query.message is a Message, which is guaranteed by
    # @ensure_message_context
    await cast(Message, query.message).edit_text(
        text, reply_markup=keyboard, parse_mode="HTML"
    )
    await query.answer()
