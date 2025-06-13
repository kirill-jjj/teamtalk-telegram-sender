"""
Keyboard utilities for the Telegram bot.

This module provides functions to generate and manage custom keyboards
for Telegram interactions using InlineKeyboardBuilder.
"""

import html
import pytalk # For UserAccount type hint
from typing import Callable, List # Added List
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants.enums import (
    AdminAction,
    SettingsNavAction,
    LanguageAction,
    SubscriptionAction,
    NotificationAction,
    MuteAllAction,
    UserListAction,
    ToggleMuteSpecificAction,
    SubscriberListAction
    # PaginateUsersAction might not be directly used here if pagination is implicit
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
from bot.database.models import NotificationSetting # For subscription settings
from bot.core.user_settings import UserSpecificSettings # For notification and mute settings
from bot.core.utils import get_tt_user_display_name
from bot.constants import CALLBACK_NICKNAME_MAX_LENGTH

ttstr = pytalk.instance.sdk.ttstr # For convenience if dealing with pytalk strings

# --- Settings Keyboards ---

def create_main_settings_keyboard(_: callable) -> InlineKeyboardBuilder:
    """Creates the main settings menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("Language"), # SETTINGS_BTN_LANGUAGE
        callback_data=SettingsCallback(action=SettingsNavAction.LANGUAGE).pack()
    )
    builder.button(
        text=_("Subscription Settings"), # SETTINGS_BTN_SUBSCRIPTIONS
        callback_data=SettingsCallback(action=SettingsNavAction.SUBSCRIPTIONS).pack()
    )
    builder.button(
        text=_("Notification Settings"), # SETTINGS_BTN_NOTIFICATIONS
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack()
    )
    builder.adjust(1)
    return builder

def create_language_selection_keyboard(_: callable) -> InlineKeyboardBuilder:
    """Creates the language selection keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("English"), # language_btn_en (English source string)
        callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code="en").pack()
    )
    builder.button(
        text=_("Русский"), # language_btn_ru (English source string)
        callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code="ru").pack()
    )
    builder.button(
        text=_("⬅️ Back to Settings"), # BACK_TO_SETTINGS_BTN
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
    active_marker = _("✅ ") # ACTIVE_CHOICE_MARKER

    # English source strings for button texts
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
        text=_("⬅️ Back to Settings"), # BACK_TO_SETTINGS_BTN
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

def create_notification_settings_keyboard(
    _: callable,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_specific_settings.not_on_online_enabled
    status_text = _("Enabled") if is_noon_enabled else _("Disabled") # ENABLED_STATUS, DISABLED_STATUS
    noon_button_text = _("NOON (Not on Online): {status}").format(status=status_text) # NOTIF_SETTING_NOON_BTN_TOGGLE

    builder.button(
        text=noon_button_text,
        callback_data=NotificationActionCallback(action=NotificationAction.TOGGLE_NOON).pack()
    )
    builder.button(
        text=_("Manage Muted/Allowed Users"), # NOTIF_SETTING_MANAGE_MUTED_BTN
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    )
    builder.button(
        text=_("⬅️ Back to Settings"), # BACK_TO_SETTINGS_BTN
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

def create_manage_muted_users_keyboard(
    _: callable,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardBuilder:
    """Creates the 'Manage Muted Users' keyboard."""
    builder = InlineKeyboardBuilder()

    is_mute_all_enabled = user_specific_settings.mute_all_flag
    mute_all_status_text = _("Enabled") if is_mute_all_enabled else _("Disabled") # ENABLED_STATUS, DISABLED_STATUS
    mute_all_button_text = _("Mute All Mode: {status}").format(status=mute_all_status_text) # MUTE_ALL_BTN_TOGGLE
    builder.button(
        text=mute_all_button_text,
        callback_data=MuteAllCallback(action=MuteAllAction.TOGGLE_MUTE_ALL).pack()
    )

    if is_mute_all_enabled:
        list_users_button_text = _("View Allowed Users (Allow List)") # LIST_ALLOWED_USERS_BTN
        list_users_cb_data = UserListCallback(action=UserListAction.LIST_ALLOWED).pack()
    else:
        list_users_button_text = _("View Muted Users (Block List)") # LIST_MUTED_USERS_BTN
        list_users_cb_data = UserListCallback(action=UserListAction.LIST_MUTED).pack()
    builder.button(text=list_users_button_text, callback_data=list_users_cb_data)

    builder.button(
        text=_("Mute/Unmute from Server List"), # MUTE_FROM_SERVER_LIST_BTN
        callback_data=UserListCallback(action=UserListAction.LIST_ALL_ACCOUNTS).pack()
    )
    builder.button(
        text=_("⬅️ Back to Notification Settings"), # BACK_TO_NOTIF_SETTINGS_BTN
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
                text=_("⬅️ Prev"), # PAGINATION_PREV_BTN
                callback_data=callback_factory(list_type=list_type, page=current_page - 1).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"), # PAGINATION_NEXT_BTN
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
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""
    builder = InlineKeyboardBuilder()

    for idx, username in enumerate(page_items):
        is_in_set = username in user_specific_settings.muted_users_set
        effectively_muted: bool
        if user_specific_settings.mute_all_flag:
            effectively_muted = not is_in_set
        else:
            effectively_muted = is_in_set

        button_text_src = "Unmute {username}" if effectively_muted else "Mute {username}" # UNMUTE_USER_BTN, MUTE_USER_BTN
        button_text = _(button_text_src).format(username=username)

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
        text=_("⬅️ Back to Mute Management"), # BACK_TO_MANAGE_MUTED_BTN
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    ))
    return builder.as_markup()

def create_account_list_keyboard(
    _: callable,
    page_items: list[pytalk.UserAccount],
    current_page: int,
    total_pages: int,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of all server user accounts."""
    builder = InlineKeyboardBuilder()

    for idx, account_obj in enumerate(page_items):
        username_str = ttstr(account_obj.username)
        display_name = username_str

        is_in_set = username_str in user_specific_settings.muted_users_set
        effectively_muted: bool
        if user_specific_settings.mute_all_flag:
            effectively_muted = not is_in_set
        else:
            effectively_muted = is_in_set

        current_status_text_src = "Muted" if effectively_muted else "Not Muted" # MUTED_STATUS, NOT_MUTED_STATUS
        current_status_text = _(current_status_text_src)

        button_text = _("{username} (Status: {current_status})").format(username=display_name, current_status=current_status_text) # TOGGLE_MUTE_STATUS_BTN

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
        text=_("⬅️ Back to Mute Management"), # BACK_TO_MANAGE_MUTED_BTN
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    ))
    return builder.as_markup()

# Note: The original show_user_buttons for kick/ban in callbacks.py was dynamic based on users online.
# Replicating that as a static factory here might be less useful unless generalized.
# For now, focusing on the settings-related keyboards as per the main structure of the request.
# The kick/ban buttons were also simpler and directly constructed in the handler.
# If a generic "select user from list" keyboard factory is needed, it would be a new addition.

def create_subscriber_list_keyboard(
    _: Callable,
    subscribers_info: List[dict], # Changed from subscriber_ids: list[int]
    current_page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the subscriber list."""
    builder = InlineKeyboardBuilder()

    # Subscriber buttons (one per row)
    for subscriber in subscribers_info: # Changed loop variable and iteration
        # Using display_name for text and telegram_id for callback
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

    # No specific builder.adjust(1) needed here as builder.row() already creates one row per button.
    # If subscribers_info is empty, no subscriber buttons will be added.

    # Pagination buttons row
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
        builder.row(*pagination_buttons) # Add them in a single row

    # Optionally, add a back button if needed, e.g., back to main menu or settings
    # builder.row(InlineKeyboardButton(text=_("⬅️ Back"), callback_data=SomeOtherCallback().pack()))

    return builder.as_markup()

# End of bot/telegram_bot/keyboards.py

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

        # Убедимся, что user_id существует и является валидным
        if not hasattr(user_obj, 'id'):
            continue
        user_id = user_obj.id

        # Используем AdminActionCallback вместо "магической строки"
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
