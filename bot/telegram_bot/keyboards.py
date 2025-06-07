
"""
Keyboard utilities for the Telegram bot.

This module provides functions to generate and manage custom keyboards
for Telegram interactions using InlineKeyboardBuilder.
"""

import hashlib # Added import
import pytalk # For UserAccount type hint
from typing import Callable
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton # Only if builder.button is insufficient

from bot.localization import get_text
from bot.telegram_bot.callback_data import (
    SettingsCallback,
    LanguageCallback,
    SubscriptionCallback,
    NotificationActionCallback,
    MuteAllCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback
)
from bot.database.models import NotificationSetting # For subscription settings
from bot.core.user_settings import UserSpecificSettings # For notification and mute settings

ttstr = pytalk.instance.sdk.ttstr # For convenience if dealing with pytalk strings

# --- Settings Keyboards ---

def create_main_settings_keyboard(language: str) -> InlineKeyboardBuilder:
    """Creates the main settings menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=get_text("SETTINGS_BTN_LANGUAGE", language),
        callback_data=SettingsCallback(action="language").pack()
    )
    builder.button(
        text=get_text("SETTINGS_BTN_SUBSCRIPTIONS", language),
        callback_data=SettingsCallback(action="subscriptions").pack()
    )
    builder.button(
        text=get_text("SETTINGS_BTN_NOTIFICATIONS", language),
        callback_data=SettingsCallback(action="notifications").pack()
    )
    builder.adjust(1)  # Each button on a new row
    return builder

def create_language_selection_keyboard(language: str) -> InlineKeyboardBuilder:
    """Creates the language selection keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=get_text("language_btn_en", language), # Assuming "English (US)" from original
        callback_data=LanguageCallback(action="set_lang", lang_code="en").pack()
    )
    builder.button(
        text=get_text("language_btn_ru", language), # Assuming "Русский (RU)" from original
        callback_data=LanguageCallback(action="set_lang", lang_code="ru").pack()
    )
    builder.button(
        text=get_text("BACK_TO_SETTINGS_BTN", language),
        callback_data=SettingsCallback(action="back_to_main").pack()
    )
    builder.adjust(1)
    return builder

def create_subscription_settings_keyboard(
    language: str,
    current_setting: NotificationSetting
) -> InlineKeyboardBuilder:
    """Creates the subscription settings keyboard."""
    builder = InlineKeyboardBuilder()
    active_marker = get_text("ACTIVE_CHOICE_MARKER", language)

    settings_map = {
        NotificationSetting.ALL: ("SUBS_SETTING_ALL_BTN", "all"),
        NotificationSetting.LEAVE_OFF: ("SUBS_SETTING_JOIN_ONLY_BTN", "leave_off"),
        NotificationSetting.JOIN_OFF: ("SUBS_SETTING_LEAVE_ONLY_BTN", "join_off"),
        NotificationSetting.NONE: ("SUBS_SETTING_NONE_BTN", "none"),
    }

    for setting_enum, (text_key, val_str) in settings_map.items():
        prefix = active_marker if current_setting == setting_enum else ""
        button_text = f"{prefix}{get_text(text_key, language)}"
        builder.button(
            text=button_text,
            callback_data=SubscriptionCallback(action="set_sub", setting_value=val_str).pack()
        )

    builder.button(
        text=get_text("BACK_TO_SETTINGS_BTN", language),
        callback_data=SettingsCallback(action="back_to_main").pack()
    )
    builder.adjust(1) # Each button on a new row
    return builder

def create_notification_settings_keyboard(
    language: str,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_specific_settings.not_on_online_enabled
    status_text = get_text("ENABLED_STATUS" if is_noon_enabled else "DISABLED_STATUS", language)
    noon_button_text = get_text("NOTIF_SETTING_NOON_BTN_TOGGLE", language, status=status_text)

    builder.button(
        text=noon_button_text,
        callback_data=NotificationActionCallback(action="toggle_noon").pack()
    )
    builder.button(
        text=get_text("NOTIF_SETTING_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    )
    builder.button(
        text=get_text("BACK_TO_SETTINGS_BTN", language),
        callback_data=SettingsCallback(action="back_to_main").pack()
    )
    builder.adjust(1)
    return builder

def create_manage_muted_users_keyboard(
    language: str,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardBuilder:
    """Creates the 'Manage Muted Users' keyboard."""
    builder = InlineKeyboardBuilder()

    is_mute_all_enabled = user_specific_settings.mute_all_flag
    mute_all_status_text = get_text("ENABLED_STATUS" if is_mute_all_enabled else "DISABLED_STATUS", language)
    mute_all_button_text = get_text("MUTE_ALL_BTN_TOGGLE", language, status=mute_all_status_text)
    builder.button(
        text=mute_all_button_text,
        callback_data=MuteAllCallback(action="toggle_mute_all").pack()
    )

    if is_mute_all_enabled:
        list_users_button_text = get_text("LIST_ALLOWED_USERS_BTN", language)
        list_users_cb_data = UserListCallback(action="list_allowed").pack()
    else:
        list_users_button_text = get_text("LIST_MUTED_USERS_BTN", language)
        list_users_cb_data = UserListCallback(action="list_muted").pack()
    builder.button(text=list_users_button_text, callback_data=list_users_cb_data)

    builder.button(
        text=get_text("MUTE_FROM_SERVER_LIST_BTN", language),
        callback_data=UserListCallback(action="list_all_accounts").pack()
    )
    builder.button(
        text=get_text("BACK_TO_NOTIF_SETTINGS_BTN", language),
        callback_data=SettingsCallback(action="notifications").pack() # Corrected: back to Notification Settings main
    )
    builder.adjust(1)
    return builder

# --- Paginated List Keyboards ---

def _add_pagination_controls(
    builder: InlineKeyboardBuilder,
    language: str,
    current_page: int,
    total_pages: int,
    list_type: str,
    callback_factory: Callable
) -> None:
    """Adds pagination controls (Previous/Next) to the keyboard builder."""
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=get_text("PAGINATION_PREV_BTN", language),
                callback_data=callback_factory(list_type=list_type, page=current_page - 1).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=get_text("PAGINATION_NEXT_BTN", language),
                callback_data=callback_factory(list_type=list_type, page=current_page + 1).pack()
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


def create_paginated_user_list_keyboard(
    language: str,
    page_slice: list[str], # Renamed from page_users
    page: int,             # Renamed from current_page for consistency
    total_pages: int,
    list_type: str, # "muted" or "allowed"
) -> InlineKeyboardBuilder:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""
    builder = InlineKeyboardBuilder()

    for idx, username in enumerate(page_slice): # Iterate over page_slice
        button_text_key = "UNMUTE_USER_BTN" if list_type == "muted" else "MUTE_USER_BTN"
        button_text = get_text(button_text_key, language, username=username)
        callback_d = ToggleMuteSpecificCallback(
            action="toggle_user",
            user_idx=idx, # Index within the current page
            current_page=page, # Use renamed page parameter
            list_type=list_type
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    # Adjust rows for user buttons, e.g., 1 per row if many, or more if few. Defaulting to 1.
    if page_slice: # Check page_slice
        builder.adjust(1)

    _add_pagination_controls(builder, language, page, total_pages, list_type, PaginateUsersCallback) # Pass page

    builder.row(InlineKeyboardButton( # Use .row() to ensure it's on its own line
        text=get_text("BACK_TO_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    ))
    return builder

def create_account_list_keyboard(
    language: str,
    page_slice: list[pytalk.UserAccount], # Renamed
    page: int,                            # Renamed
    total_pages: int,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardBuilder:
    """Creates keyboard for a paginated list of all server user accounts."""
    builder = InlineKeyboardBuilder()

    for idx, account_obj in enumerate(page_slice): # Iterate over page_slice
        username_str = ttstr(account_obj._account.szUsername)
        username_hash = hashlib.sha1(username_str.encode('utf-8')).hexdigest()
        # Nickname for display purposes; for UserAccount, username is the primary identifier.
        display_name = username_str

        is_in_set = username_str in user_specific_settings.muted_users_set
        is_effectively_muted = (user_specific_settings.mute_all_flag and not is_in_set) or \
                               (not user_specific_settings.mute_all_flag and is_in_set)

        current_status_text = get_text("MUTED_STATUS" if is_effectively_muted else "NOT_MUTED_STATUS", language)
        button_text = get_text("TOGGLE_MUTE_STATUS_BTN", language, username=display_name, current_status=current_status_text)

        callback_d = ToggleMuteSpecificCallback(
            action="toggle_user",
            username_hash=username_hash, # Use the calculated hash
            current_page=page, # Use renamed page parameter
            list_type="all_accounts" # Specific list type for server accounts
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    if page_slice: # Check page_slice
        builder.adjust(1) # User buttons one per row

    _add_pagination_controls(builder, language, page, total_pages, "all_accounts", PaginateUsersCallback) # Pass page

    builder.row(InlineKeyboardButton( # Back button on its own row
        text=get_text("BACK_TO_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    ))
    return builder

# Note: The original show_user_buttons for kick/ban in callbacks.py was dynamic based on users online.
# Replicating that as a static factory here might be less useful unless generalized.
# For now, focusing on the settings-related keyboards as per the main structure of the request.
# The kick/ban buttons were also simpler and directly constructed in the handler.
# If a generic "select user from list" keyboard factory is needed, it would be a new addition.

# End of bot/telegram_bot/keyboards.py
