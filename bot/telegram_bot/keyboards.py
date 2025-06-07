"""
Keyboard utilities for the Telegram bot.

This module provides functions to generate and manage custom keyboards
for Telegram interactions using InlineKeyboardBuilder.
"""

import html
import pytalk # For UserAccount type hint
from typing import Callable
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
from bot.core.utils import get_tt_user_display_name
from bot.constants import CALLBACK_NICKNAME_MAX_LENGTH

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
    page_items: list[str], # Usernames
    current_page: int,
    total_pages: int,
    list_type: str, # "muted" or "allowed"
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""
    builder = InlineKeyboardBuilder()

    # Determine button text based on list_type AND actual mute status considering mute_all_flag
    # This logic was simplified in the original user code, but for correctness:
    for idx, username in enumerate(page_items):
        is_in_set = username in user_specific_settings.muted_users_set

        # If mute_all_flag is True, the set contains ALLOWED users.
        #   - If user is in set (allowed), they are NOT effectively muted. Button should offer to MUTE.
        #   - If user is NOT in set (not allowed), they ARE effectively muted. Button should offer to UNMUTE.
        # If mute_all_flag is False, the set contains MUTED users.
        #   - If user is in set (muted), they ARE effectively muted. Button should offer to UNMUTE.
        #   - If user is NOT in set (not muted), they are NOT effectively muted. Button should offer to MUTE.

        effectively_muted: bool
        if user_specific_settings.mute_all_flag: # Mute all is ON, set has allowed users
            effectively_muted = not is_in_set
        else: # Mute all is OFF, set has muted users
            effectively_muted = is_in_set

        button_text_key = "UNMUTE_USER_BTN" if effectively_muted else "MUTE_USER_BTN"

        button_text = get_text(button_text_key, language, username=username)
        callback_d = ToggleMuteSpecificCallback(
            action="toggle_user",
            user_idx=idx, # Index within the current page
            current_page=current_page,
            list_type=list_type
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    # Adjust rows for user buttons, e.g., 1 per row if many, or more if few. Defaulting to 1.
    if page_items:
        builder.adjust(1)

    _add_pagination_controls(builder, language, current_page, total_pages, list_type, PaginateUsersCallback)

    builder.row(InlineKeyboardButton( # Use .row() to ensure it's on its own line
        text=get_text("BACK_TO_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    ))
    return builder.as_markup()

def create_account_list_keyboard(
    language: str,
    page_items: list[pytalk.UserAccount], # List of UserAccount objects for the current page
    current_page: int,
    total_pages: int,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of all server user accounts."""
    builder = InlineKeyboardBuilder()

    for idx, account_obj in enumerate(page_items):
        # Ensure correct attribute access for username, ttstr should be available
        username_str = ttstr(account_obj.username) # Assuming .username based on UserAccount objects
        display_name = username_str # For UserAccount, username is typically the display name

        # Determine mute status for button text
        is_in_set = username_str in user_specific_settings.muted_users_set
        effectively_muted: bool
        if user_specific_settings.mute_all_flag: # Mute all is ON, set has allowed users
            effectively_muted = not is_in_set
        else: # Mute all is OFF, set has muted users
            effectively_muted = is_in_set

        current_status_text_key = "MUTED_STATUS" if effectively_muted else "NOT_MUTED_STATUS"
        current_status_text = get_text(current_status_text_key, language)

        # Button text should indicate the action to be taken (e.g., "Mute X" or "Unmute X")
        # or show current status and allow toggle, e.g. "X (Muted) - Tap to Unmute"
        # The prompt uses "TOGGLE_MUTE_STATUS_BTN" which implies a dynamic label.
        button_text = get_text("TOGGLE_MUTE_STATUS_BTN", language, username=display_name, current_status=current_status_text)

        callback_d = ToggleMuteSpecificCallback(
            action="toggle_user",
            user_idx=idx, # Index within the current page
            current_page=current_page,
            list_type="all_accounts" # Specific list type for server accounts
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    if page_items: # Check page_items now
        builder.adjust(1) # User buttons one per row

    _add_pagination_controls(builder, language, current_page, total_pages, "all_accounts", PaginateUsersCallback)

    builder.row(InlineKeyboardButton( # Back button on its own row
        text=get_text("BACK_TO_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    ))
    return builder.as_markup()

# Note: The original show_user_buttons for kick/ban in callbacks.py was dynamic based on users online.
# Replicating that as a static factory here might be less useful unless generalized.
# For now, focusing on the settings-related keyboards as per the main structure of the request.
# The kick/ban buttons were also simpler and directly constructed in the handler.
# If a generic "select user from list" keyboard factory is needed, it would be a new addition.

# End of bot/telegram_bot/keyboards.py

def create_user_selection_keyboard(
    language: str,
    users_to_display: list[pytalk.user.User], # Use specific type if available, e.g., TeamTalkUser
    command_type: str
) -> InlineKeyboardBuilder:
    """
    Creates a keyboard with buttons for each user in the provided list.
    """
    builder = InlineKeyboardBuilder()

    for user_obj in users_to_display:
        # Ensure user_obj is not None if the list can contain None values, though filtering should happen before.
        if not user_obj:
            continue

        user_nickname_val = get_tt_user_display_name(user_obj, language)

        # Safely access nickname and username, providing defaults
        raw_nickname = ttstr(user_obj.nickname) if hasattr(user_obj, 'nickname') and user_obj.nickname is not None else ""
        raw_username = ttstr(user_obj.username) if hasattr(user_obj, 'username') and user_obj.username is not None else ""

        # Determine callback_nickname_val ensuring it's not empty and respects max length
        # Use username if nickname is empty. If both are empty, use "unknown".
        effective_name_for_callback = raw_nickname or raw_username or "unknown"
        callback_nickname_val = effective_name_for_callback[:CALLBACK_NICKNAME_MAX_LENGTH]

        # Ensure user_obj.id is accessible
        user_id = user_obj.id if hasattr(user_obj, 'id') else "unknown_id"
        if user_id == "unknown_id":
            # Potentially log a warning here if user_id is critical and missing
            # logger.warning(f"User object missing 'id' attribute: {user_obj}")
            continue # Skip user if ID is missing, as callback would be invalid

        builder.button(
            text=html.quote(user_nickname_val), # Display name, quoted
            callback_data=f"{command_type}:{user_id}:{callback_nickname_val}"
        )

    builder.adjust(2) # Adjust to 2 buttons per row
    return builder
