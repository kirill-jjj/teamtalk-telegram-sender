from collections.abc import Awaitable, Callable
import functools
import gettext
import logging
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberActionCallback,
)
from bot.telegram_bot.keyboards import create_subscriber_action_menu_keyboard
from bot.telegram_bot.ui_utils import safe_edit_text
from bot.telegram_bot.utils import format_telegram_user_display_name

if TYPE_CHECKING:
    from bot.services_container import Services


logger = logging.getLogger(__name__)

__all__ = [
    "_display_subscriber_view",
    "action_and_refresh_view",
    "create_setting_change_handler",
    "ensure_message_context",
    "refresh_subscriber_view",
    "safe_edit_text",
]

RefreshableViewCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberNotificationPrefCallback
    | AdminSetSubscriberMuteModeCallback
    | SubscriberActionCallback
)


ViewRefresher: TypeAlias = Callable[..., Awaitable[None]]


def action_and_refresh_view(
    view_refresher: ViewRefresher,
) -> Callable[[Callable[..., Awaitable[tuple[bool, str]]]], Callable[..., Awaitable[None]]]:
    """Decorator factory for actions that result in refreshing a view.

    - It calls the wrapped handler, which should perform an action and return a (success, message) tuple.
    - It answers the callback query with the message.
    - It calls the provided `view_refresher` function to update the UI.

    :param view_refresher: An async function that handles the UI refresh logic.
    :return: A decorator.
    """

    def decorator(
        func: Callable[..., Awaitable[tuple[bool, str]]],
    ) -> Callable[..., Awaitable[None]]:
        @functools.wraps(func)
        async def wrapper(
            query: CallbackQuery,
            callback_data: Any,  # noqa: ANN401 Keep it generic to support various callbacks
            session: AsyncSession,
            translator: gettext.GNUTranslations,
            services: "Services",
            **kwargs: object,
        ) -> None:
            # The @ensure_message_context decorator should be applied before this one,
            # so we can assume query.message is not None.

            # 1. Call the wrapped handler to perform the core action
            success, message = await func(
                query=query,
                callback_data=callback_data,
                session=session,
                translator=translator,
                services=services,
                **kwargs,
            )

            # 2. Answer the callback query with the result message
            await query.answer(message, show_alert=not success)

            # 3. Call the provided view refresher function to refresh the UI
            await view_refresher(
                query=query,
                callback_data=callback_data,
                session=session,
                translator=translator,
                services=services,
                **kwargs,
            )

        return wrapper

    return decorator


async def refresh_subscriber_view(
    query: CallbackQuery,
    callback_data: RefreshableViewCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    **kwargs: object,
) -> None:
    """Refresher function for the subscriber detail view."""
    # This function is designed to be used with the `action_and_refresh_view` decorator.
    target_telegram_id = callback_data.target_telegram_id

    # The page context attribute can have different names in different callbacks.
    if hasattr(callback_data, "subscriber_page_context"):
        page_context = callback_data.subscriber_page_context
    elif hasattr(callback_data, "page"):
        page_context = callback_data.page
    else:
        logger.warning(
            "Could not determine page context from callback_data. Defaulting to page 0.",
        )
        page_context = 0

    # Call the view rendering function to refresh the UI
    await _display_subscriber_view(
        query=query,
        target_telegram_id=target_telegram_id,
        page_context=page_context,
        session=session,
        translator=translator,
        services=services,
    )


def ensure_message_context(
    func: Callable[..., Awaitable[Any | None]],
) -> Callable[..., Awaitable[Any | None]]:
    """Decorator to ensure that a callback query handler has a message context.

    If query.message is None, it logs an error and attempts to answer the callback query.
    """

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,  # Keep query as first arg for clarity in wrapper
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any | None:  # noqa: ANN401
        # I18nMiddleware is expected to inject 'translator' into kwargs
        translator = kwargs.get("translator")

        if not isinstance(translator, gettext.GNUTranslations):
            # This is an unexpected situation if middlewares are correctly configured.
            logger.critical(
                "Translator object not found or not a GNUTranslations instance in handler '%s' context! "
                "Check middleware order/injection. Falling back to NullTranslations.",
                func.__name__,
            )
            translator = gettext.NullTranslations()

        _ = translator.gettext

        # This message is specifically for the case where query.message is None
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
                logger.exception("Failed to answer callback query in decorator for '%s'.", func.__name__)
            return None  # Stop further execution of the handler

        return await func(query, *args, **kwargs)

    return wrapper


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Helper function to display the subscriber details view."""
    _ = translator.gettext

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    user_to_view = await session.get(UserSettings, target_telegram_id)
    display_name = str(target_telegram_id)

    active_bot = services.bot_event
    if user_to_view and user_to_view.telegram_id:
        try:
            chat_info = await active_bot.get_chat(user_to_view.telegram_id)
            display_name = format_telegram_user_display_name(chat_info)
        except TelegramAPIError:
            logger.exception("Could not fetch chat info for %s via Telegram API.", user_to_view.telegram_id)
        except Exception:
            logger.exception("Unexpected error fetching chat info for %s.", user_to_view.telegram_id)

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    if user_to_view:
        details_parts.append(
            _("Linked TT Account: {tt_username}").format(tt_username=user_to_view.teamtalk_username or _("None"))
        )
        details_parts.append(_("Language: {lang}").format(lang=user_to_view.language_code))
        noon_status = _("Enabled") if user_to_view.not_on_online_enabled else _("Disabled")
        details_parts.append(_("NOON (Not on Online): {status}").format(status=noon_status))
        notif_setting_map = {
            NotificationSetting.ALL.value: _("All (Join & Leave)"),
            NotificationSetting.LEAVE_OFF.value: _("Join Only"),
            NotificationSetting.JOIN_OFF.value: _("Leave Only"),
            NotificationSetting.NONE.value: _("None"),
        }
        notif_setting_str = user_to_view.notification_settings.value
        details_parts.append(
            _("Notifications: {setting}").format(setting=notif_setting_map.get(notif_setting_str, notif_setting_str))
        )
        mute_mode_str = _("Blacklist") if user_to_view.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        details_parts.append(_("Mute Mode: {mode}").format(mode=mute_mode_str))
    else:
        details_parts.append(_("Subscriber settings not found."))

    text = "\n".join(details_parts)
    # This assumes query.message is a Message, which is guaranteed by @ensure_message_context
    await cast(Message, query.message).edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await query.answer()


def create_setting_change_handler(
    service_func: Callable[[AsyncSession, "Services", int, Any], Awaitable[UserSettings | None]],
    value_extractor: Callable[[Any], Any],
    success_msg_formatter: str,
    failure_msg: str,
) -> Callable[..., Awaitable[tuple[bool, str]]]:
    """Creates a generic handler for changing a subscriber's setting.

    :param service_func: The admin service function to call.
    :param value_extractor: A function to extract the new value from callback_data.
    :param success_msg_formatter: The format string for the success message.
    :param failure_msg: The static string for the failure message.
    :return: An async handler function.
    """

    async def handler(
        query: CallbackQuery,
        callback_data: RefreshableViewCallback,
        session: AsyncSession,
        translator: gettext.GNUTranslations,
        services: "Services",
        **kwargs: object,
    ) -> tuple[bool, str]:
        _ = translator.gettext
        target_telegram_id = callback_data.target_telegram_id
        new_value = value_extractor(callback_data)

        updated_user_settings = await service_func(session, services, target_telegram_id, new_value)

        if updated_user_settings:
            message = _(success_msg_formatter).format(tg_id=target_telegram_id, value=new_value)
            return True, message
        return False, _(failure_msg)

    return handler
