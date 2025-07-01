# bot/telegram_bot/keyboards.py

"""
Keyboard utilities for the Telegram bot.

This module provides functions to generate and manage custom keyboards
for Telegram interactions using InlineKeyboardBuilder.
"""

import html
import pytalk # For UserAccount type hint
from typing import Callable, List
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.core.enums import (
    AdminAction,
    SettingsNavAction,
    LanguageAction,
    SubscriptionAction,
    NotificationAction,
    MuteAllAction,
    UserListAction,
    ToggleMuteSpecificAction,
    SubscriberListAction
)
from bot.telegram_bot.callback_data import (
    SettingsCallback,
    LanguageCallback,
    SubscriptionCallback,
    NotificationActionCallback,
    MuteAllCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback,
    AdminActionCallback,
    SubscriberListCallback
)
from bot.models import NotificationSetting, UserSettings # MutedUser might be needed if we pass MutedUser objects
from bot.core.utils import get_tt_user_display_name
from bot.constants import CALLBACK_NICKNAME_MAX_LENGTH

ttstr = pytalk.instance.sdk.ttstr


# --- Helper Functions ---

def _is_username_effectively_muted(username: str, user_settings: UserSettings, muted_usernames_set: set[str]) -> bool:
    """
    Determines if a username is effectively muted based on user settings and a provided set of muted/allowed usernames.
    - If user_settings.mute_all is True, the set is an allow list; user is muted if NOT in the set.
    - If user_settings.mute_all is False, the set is a block list; user is muted if IN the set.
    """
    is_in_set = username in muted_usernames_set
    if user_settings.mute_all:
        return not is_in_set  # Muted if not in the allow list
    else:
        return is_in_set      # Muted if in the block list

# --- Settings Keyboards ---

def create_main_settings_keyboard(_: callable) -> InlineKeyboardBuilder:
    """Creates the main settings menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("Language"),
        callback_data=SettingsCallback(action=SettingsNavAction.LANGUAGE).pack()
    )
    builder.button(
        text=_("Subscription Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.SUBSCRIPTIONS).pack()
    )
    builder.button(
        text=_("Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack()
    )
    builder.adjust(1)
    return builder

def create_language_selection_keyboard(_: callable) -> InlineKeyboardBuilder:
    """Creates the language selection keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("English"),
        callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code="en").pack()
    )
    builder.button(
        text=_("Russian"),
        callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code="ru").pack()
    )
    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

def create_subscription_settings_keyboard(
    _: callable,
    current_setting: NotificationSetting
) -> InlineKeyboardBuilder:
    """Creates the subscription settings keyboard."""
    builder = InlineKeyboardBuilder()
    active_marker = _("✅ ")

    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", "all"),
        NotificationSetting.LEAVE_OFF: ("Join Only", "leave_off"),
        NotificationSetting.JOIN_OFF: ("Leave Only", "join_off"),
        NotificationSetting.NONE: ("None", "none"),
    }

    for setting_enum, (text_source, val_str) in settings_map_source.items():
        prefix = active_marker if current_setting == setting_enum else ""
        button_text = f"{prefix}{_(text_source)}"
        builder.button(
            text=button_text,
            callback_data=SubscriptionCallback(action=SubscriptionAction.SET_SUB, setting_value=val_str).pack()
        )

    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

def create_notification_settings_keyboard(
    _: callable,
    user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_settings.not_on_online_enabled
    status_text = _("Enabled") if is_noon_enabled else _("Disabled")
    noon_button_text = _("NOON (Not on Online): {status}").format(status=status_text)

    builder.button(
        text=noon_button_text,
        callback_data=NotificationActionCallback(action=NotificationAction.TOGGLE_NOON).pack()
    )
    builder.button(
        text=_("Manage Muted/Allowed Users"),
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    )
    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

def create_manage_muted_users_keyboard(
    _: callable,
    user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the 'Manage Muted Users' keyboard."""
    builder = InlineKeyboardBuilder()

    is_mute_all_enabled = user_settings.mute_all # Field name changed from mute_all_flag
    mute_all_status_text = _("Enabled") if is_mute_all_enabled else _("Disabled")
    mute_all_button_text = _("Mute All Mode: {status}").format(status=mute_all_status_text)
    builder.button(
        text=mute_all_button_text,
        callback_data=MuteAllCallback(action=MuteAllAction.TOGGLE_MUTE_ALL).pack()
    )

    if is_mute_all_enabled:
        list_users_button_text = _("View Allowed Users (Allow List)")
        list_users_cb_data = UserListCallback(action=UserListAction.LIST_ALLOWED).pack()
    else:
        list_users_button_text = _("View Muted Users (Block List)")
        list_users_cb_data = UserListCallback(action=UserListAction.LIST_MUTED).pack()
    builder.button(text=list_users_button_text, callback_data=list_users_cb_data)

    builder.button(
        text=_("Mute/Unmute from Server List"),
        callback_data=UserListCallback(action=UserListAction.LIST_ALL_ACCOUNTS).pack()
    )
    builder.button(
        text=_("⬅️ Back to Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack()
    )
    builder.adjust(1)
    return builder

# --- Paginated List Keyboards ---

def _add_pagination_controls(
    builder: InlineKeyboardBuilder,
    _: callable,
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    callback_factory: Callable
) -> None:
    """Adds pagination controls (Previous/Next) to the keyboard builder."""
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=callback_factory(list_type=list_type, page=current_page - 1).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=callback_factory(list_type=list_type, page=current_page + 1).pack()
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


def create_paginated_user_list_keyboard(
    _: callable,
    page_items: list[str],
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    user_settings: UserSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""
    builder = InlineKeyboardBuilder()

    # Create a set of muted usernames from the user_settings.muted_users_list relationship
    # This list contains MutedUser objects.
    muted_usernames_from_relationship = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}

    for idx, username in enumerate(page_items):
        # page_items are strings (usernames)
        effectively_muted = _is_username_effectively_muted(username, user_settings, muted_usernames_from_relationship)

        button_text = _("Unmute {username}").format(username=username) if effectively_muted else _("Mute {username}").format(username=username)

        callback_d = ToggleMuteSpecificCallback(
            action=ToggleMuteSpecificAction.TOGGLE_USER,
            user_idx=idx,
            current_page=current_page,
            list_type=list_type
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    if page_items:
        builder.adjust(1)

    _add_pagination_controls(builder, _, current_page, total_pages, list_type, PaginateUsersCallback)

    builder.row(InlineKeyboardButton(
        text=_("⬅️ Back to Mute Management"),
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    ))
    return builder.as_markup()

def create_account_list_keyboard(
    _: callable,
    page_items: list[pytalk.UserAccount],
    current_page: int,
    total_pages: int,
    user_settings: UserSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of all server user accounts."""
    builder = InlineKeyboardBuilder()

    # Create a set of muted usernames from the user_settings.muted_users_list relationship
    muted_usernames_from_relationship = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}

    for idx, account_obj in enumerate(page_items):
        username_str = ttstr(account_obj.username)
        display_name = username_str

        effectively_muted = _is_username_effectively_muted(username_str, user_settings, muted_usernames_from_relationship)

        current_status_text = _("Muted") if effectively_muted else _("Not Muted")

        button_text = _("{username} (Status: {current_status})").format(username=display_name, current_status=current_status_text)

        callback_d = ToggleMuteSpecificCallback(
        action=ToggleMuteSpecificAction.TOGGLE_USER,
            user_idx=idx,
            current_page=current_page,
        list_type=UserListAction.LIST_ALL_ACCOUNTS
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    if page_items:
        builder.adjust(1)

    _add_pagination_controls(builder, _, current_page, total_pages, UserListAction.LIST_ALL_ACCOUNTS, PaginateUsersCallback)

    builder.row(InlineKeyboardButton(
        text=_("⬅️ Back to Mute Management"),
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    ))
    return builder.as_markup()

def create_subscriber_list_keyboard(
    _: Callable,
    page_subscribers_info: List[dict],
    current_page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the subscriber list."""
    builder = InlineKeyboardBuilder()

    for subscriber in page_subscribers_info:
        button_text = _("Delete {user_info}").format(user_info=subscriber['display_name'])
        builder.row(
            InlineKeyboardButton(
                text=button_text,
                callback_data=SubscriberListCallback(
                    action=SubscriberListAction.DELETE_SUBSCRIBER,
                    telegram_id=subscriber['telegram_id'], # Using telegram_id from dict
                    page=current_page  # Keep track of current page for refresh
                ).pack()
            )
        )

    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=SubscriberListCallback(
                    action=SubscriberListAction.PAGE,
                    page=current_page - 1
                ).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=SubscriberListCallback(
                    action=SubscriberListAction.PAGE,
                    page=current_page + 1
                ).pack()
            )
        )

    if pagination_buttons:
        builder.row(*pagination_buttons)

    return builder.as_markup()

def create_user_selection_keyboard(
    _: callable,
    users_to_display: list[pytalk.user.User],
    command_type: AdminAction
) -> InlineKeyboardBuilder:
    """
    Creates a keyboard with buttons for each user in the provided list.
    """
    builder = InlineKeyboardBuilder()

    for user_obj in users_to_display:
        if not user_obj:
            continue

        user_nickname = get_tt_user_display_name(user_obj, _)

        if not hasattr(user_obj, 'id'):
            continue
        user_id = user_obj.id

        callback_data = AdminActionCallback(
            action=command_type,
            user_id=user_id
        ).pack()

        builder.button(
            text=html.escape(user_nickname),
            callback_data=callback_data
        )

    builder.adjust(2)
    return builder
