"""Callback query handlers for an admin managing a subscriber's settings."""

from collections.abc import Awaitable, Callable
import gettext
import logging
from typing import TYPE_CHECKING, Any, TypedDict, cast

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.constants import MUTE_LIST_ITEMS_PER_PAGE
from bot.core.enums import SubscriberCommand
from bot.models import (
    MutedUser,
    MuteListMode,
    NotificationSetting,
    UserSettings,
)
from bot.services import admin_service
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    PaginateMuteListCallback,
    SubscriberCallback,
)
from bot.telegram_bot.handlers.callback_handlers._helpers import (
    ensure_message_context,
    refresh_subscriber_view,
    with_view_refresh,
)
from bot.telegram_bot.keyboards import (
    create_admin_subscriber_lang_keyboard,
    create_admin_subscriber_mute_mode_keyboard,
    create_admin_subscriber_notification_pref_keyboard,
    create_view_mute_list_keyboard,
)
from bot.telegram_bot.ui_utils import display_paginated_list
from bot.telegram_bot.utils import format_telegram_user_display_name

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup

    from bot.services_container import Services


class SettingChoiceConfig(TypedDict):
    """A type hint for the setting choice configuration dictionary."""

    message_text: str
    keyboard_factory: "Callable[..., Awaitable[InlineKeyboardMarkup]]"
    keyboard_factory_kwargs: dict[str, object]


logger = logging.getLogger(__name__)
settings_router = Router(name="subscriber_management.settings_router")


async def _present_subscriber_setting_choice(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    message_text: str,
    keyboard_factory: "Callable[..., Awaitable[InlineKeyboardMarkup]]",
    keyboard_factory_kwargs: dict[str, object],
) -> None:
    """A generic helper to present a settings choice menu to an admin for a subscriber."""
    keyboard = await keyboard_factory(**keyboard_factory_kwargs)
    await cast(Message, query.message).edit_text(message_text, reply_markup=keyboard)
    await query.answer()


@settings_router.callback_query(
    SubscriberCallback.filter(
        F.action.in_(
            [
                SubscriberCommand.ADMIN_SET_LANGUAGE,
                SubscriberCommand.ADMIN_SET_NOTIF_PREF,
                SubscriberCommand.ADMIN_SET_MUTE_MODE,
            ]
        )
    )
)
@ensure_message_context
async def admin_set_setting_choice(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles showing the choice menu for various subscriber settings to an admin."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    action = callback_data.action

    user_settings = None
    if action in [
        SubscriberCommand.ADMIN_SET_NOTIF_PREF,
        SubscriberCommand.ADMIN_SET_MUTE_MODE,
    ]:
        user_settings = await session.get(UserSettings, target_telegram_id)
        if not user_settings:
            await query.answer(_("Subscriber settings not found."), show_alert=True)
            return

    setting_choice_config: dict[SubscriberCommand, SettingChoiceConfig] = {
        SubscriberCommand.ADMIN_SET_LANGUAGE: {
            "message_text": _("Select new language for subscriber {tg_id}:").format(tg_id=target_telegram_id),
            "keyboard_factory": create_admin_subscriber_lang_keyboard,
            "keyboard_factory_kwargs": {
                "available_languages": services.available_languages,
            },
        },
        SubscriberCommand.ADMIN_SET_NOTIF_PREF: {
            "message_text": _("Select notification preference for subscriber {tg_id}:").format(
                tg_id=target_telegram_id
            ),
            "keyboard_factory": create_admin_subscriber_notification_pref_keyboard,
            "keyboard_factory_kwargs": {
                "current_setting": user_settings.notification_settings if user_settings else None,
            },
        },
        SubscriberCommand.ADMIN_SET_MUTE_MODE: {
            "message_text": _("Select mute list mode for subscriber {tg_id}:").format(tg_id=target_telegram_id),
            "keyboard_factory": create_admin_subscriber_mute_mode_keyboard,
            "keyboard_factory_kwargs": {
                "current_mode": user_settings.mute_list_mode if user_settings else None,
            },
        },
    }

    config = setting_choice_config.get(action)
    if not config:
        logger.error("No config found for action %s in handle_admin_set_setting_choice", action)
        return

    common_kwargs = {
        "translator": translator,
        "target_telegram_id": target_telegram_id,
        "subscriber_page_context": callback_data.page,
    }

    await _present_subscriber_setting_choice(
        query=query,
        callback_data=callback_data,
        message_text=config["message_text"],
        keyboard_factory=config["keyboard_factory"],
        keyboard_factory_kwargs={**config["keyboard_factory_kwargs"], **common_kwargs},
    )


@settings_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.ADMIN_TOGGLE_NOON))
@ensure_message_context
@with_view_refresh(refresh_subscriber_view)
async def admin_toggle_noon(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> tuple[bool, str]:
    """Handles an admin toggling NOON setting for a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    updated_user_settings = await admin_service.admin_toggle_noon_setting(session, services, target_telegram_id)

    if updated_user_settings:
        new_status_text = _("Enabled") if updated_user_settings.not_on_online_enabled else _("Disabled")
        message = _("NOON status for subscriber {tg_id} set to: {status}").format(
            tg_id=target_telegram_id, status=new_status_text
        )
        return True, message
    message = _("Failed to toggle NOON status. Please try again.")
    return False, message


async def _fetch_mute_list_data(
    session: AsyncSession, target_telegram_id: int, services: "Services"
) -> tuple[UserSettings | None, str]:
    """Fetches user settings and their display name for the mute list view."""
    statement = (
        select(UserSettings)
        .where(UserSettings.telegram_id == target_telegram_id)
        .options(selectinload(cast(QueryableAttribute[list[MutedUser]], UserSettings.muted_users_list)))
    )
    target_user_settings = await session.scalar(statement)

    subscriber_display_name = str(target_telegram_id)
    if target_user_settings:
        try:
            chat_info = await services.bot_event.get_chat(target_telegram_id)
            if chat_info:
                subscriber_display_name = format_telegram_user_display_name(chat_info)
        except Exception:
            logger.warning(
                "Could not fetch display name for %s in view_mute_list",
                target_telegram_id,
                exc_info=True,
            )
    return target_user_settings, subscriber_display_name


def _build_mute_list_title(
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    subscriber_display_name: str,
) -> str:
    """Builds the title for the mute list view."""
    _ = translator.gettext
    mode_text = _("Blacklist") if user_settings.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
    title_text_parts = [
        _("Mute list for subscriber: {subscriber_name} (ID: {subscriber_id})").format(
            subscriber_name=subscriber_display_name, subscriber_id=user_settings.telegram_id
        ),
        _("Mute Mode: {mode}").format(mode=mode_text),
    ]
    return "\n".join(title_text_parts)


@settings_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.ADMIN_VIEW_MUTE_LIST))
@ensure_message_context
async def admin_view_mute_list(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Entry point for an admin to view a specific subscriber's mute list."""
    await _display_subscriber_mute_list_page(
        query=query,
        session=session,
        translator=translator,
        services=services,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_list_return_page=callback_data.page,
        mute_list_page_num=0,
    )


async def _display_subscriber_mute_list_page(
    query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    target_telegram_id: int,
    subscriber_list_return_page: int,
    mute_list_page_num: int,
) -> None:
    """Displays a paginated view of a subscriber's mute list."""
    _ = translator.gettext
    target_user_settings, subscriber_display_name = await _fetch_mute_list_data(session, target_telegram_id, services)

    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        logger.info("Subscriber settings not found for %s when viewing mute list.", target_telegram_id)
        return

    if query.bot is None:
        logger.error("handle_admin_view_mute_list: query.bot is None. Cannot display list.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    all_muted_usernames = sorted([mu.muted_teamtalk_username for mu in target_user_settings.muted_users_list])
    title_text = _build_mute_list_title(translator, target_user_settings, subscriber_display_name)
    empty_list_text = _("The mute list is currently empty.")

    await display_paginated_list(
        target=query,
        bot=query.bot,
        translator=translator,
        items=all_muted_usernames,
        page=mute_list_page_num,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_view_mute_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_context_page": subscriber_list_return_page,
        },
        page_size=MUTE_LIST_ITEMS_PER_PAGE,
    )


@settings_router.callback_query(PaginateMuteListCallback.filter())
@ensure_message_context
async def paginate_mute_list(
    query: CallbackQuery,
    callback_data: PaginateMuteListCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles pagination for the admin's view of a subscriber's mute list."""
    await _display_subscriber_mute_list_page(
        query=query,
        session=session,
        translator=translator,
        services=services,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_list_return_page=callback_data.subscriber_context_page,
        mute_list_page_num=callback_data.mute_list_page,
    )
    await query.answer()


# Data-driven configuration for admin setting handlers


class AdminSettingHandlerConfig(TypedDict):
    """A type hint for the admin setting handler configuration dictionary."""

    service_func: Callable[..., Awaitable[UserSettings | None]]
    param_name: str
    value_extractor: Callable[[Any], Any]
    success_msg_formatter: str
    failure_msg: str


SETTING_HANDLERS_CONFIG: dict[type[CallbackData], AdminSettingHandlerConfig] = {
    AdminSetSubscriberLanguageCallback: {
        "service_func": admin_service.admin_set_user_language,
        "param_name": "new_lang_code",
        "value_extractor": lambda cb: cb.lang_code,
        "success_msg_formatter": "Language for subscriber {tg_id} changed to {value}.",
        "failure_msg": "Failed to change language. Subscriber settings might be missing or an error occurred.",
    },
    AdminSetSubscriberNotificationPrefCallback: {
        "service_func": admin_service.admin_set_user_notification_preference,
        "param_name": "new_pref_enum",
        "value_extractor": lambda cb: NotificationSetting(cb.setting_value),
        "success_msg_formatter": "Notification preference for subscriber {tg_id} set to: {value}.",
        "failure_msg": "Failed to change notification preference. Please check logs or try again.",
    },
    AdminSetSubscriberMuteModeCallback: {
        "service_func": admin_service.admin_set_user_mute_mode,
        "param_name": "new_mode",
        "value_extractor": lambda cb: cb.mode,
        "success_msg_formatter": "Mute list mode for subscriber {tg_id} set to: {value}.",
        "failure_msg": "Failed to change mute mode. Subscriber settings might be missing or an error occurred.",
    },
}


@settings_router.callback_query(
    AdminSetSubscriberLanguageCallback.filter(),
    AdminSetSubscriberNotificationPrefCallback.filter(),
    AdminSetSubscriberMuteModeCallback.filter(),
)
@ensure_message_context
@with_view_refresh(refresh_subscriber_view)
async def admin_set_any_subscriber_setting(
    query: CallbackQuery,
    callback_data: (
        AdminSetSubscriberLanguageCallback
        | AdminSetSubscriberNotificationPrefCallback
        | AdminSetSubscriberMuteModeCallback
    ),
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> tuple[bool, str]:
    """Handles an admin setting a specific subscriber's setting using a data-driven approach."""
    _ = translator.gettext
    config = SETTING_HANDLERS_CONFIG.get(type(callback_data))
    if not config:
        logger.error("No handler config found for callback data type: %s", type(callback_data).__name__)
        return False, _("An unexpected error occurred.")

    target_telegram_id = callback_data.target_telegram_id
    param_name = config["param_name"]
    value_to_set = config["value_extractor"](callback_data)

    # Dynamically call the appropriate service function
    service_kwargs = {
        "session": session,
        "services": services,
        "target_telegram_id": target_telegram_id,
        param_name: value_to_set,
    }
    updated_user_settings = await config["service_func"](**service_kwargs)

    if updated_user_settings:
        message = _(config["success_msg_formatter"]).format(tg_id=target_telegram_id, value=value_to_set)
        return True, message

    return False, _(config["failure_msg"])
