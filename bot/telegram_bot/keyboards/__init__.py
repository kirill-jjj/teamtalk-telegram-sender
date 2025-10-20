"""A package for creating Telegram bot keyboards.

This package consolidates all keyboard creation functions, organized into
domain-specific modules. The `__init__.py` file exposes all public keyboard
functions for easy importing.
"""

from .admin_keyboards import (
    create_admin_subscriber_lang_keyboard,
    create_admin_subscriber_mute_mode_keyboard,
    create_admin_subscriber_notification_pref_keyboard,
    create_banned_user_list_keyboard,
    create_linkable_tt_account_list_keyboard,
    create_main_menu_keyboard,
    create_manage_tt_account_keyboard,
    create_subscriber_action_menu_keyboard,
    create_subscriber_list_keyboard,
    create_user_selection_keyboard,
    create_view_mute_list_keyboard,
)
from .settings_keyboards import (
    create_language_selection_keyboard,
    create_main_settings_keyboard,
    create_manage_muted_users_keyboard,
    create_notification_settings_keyboard,
    create_subscription_settings_keyboard,
)
from .shared import create_toggle_mute_keyboard

__all__ = [
    "create_admin_subscriber_lang_keyboard",
    "create_admin_subscriber_mute_mode_keyboard",
    "create_admin_subscriber_notification_pref_keyboard",
    "create_banned_user_list_keyboard",
    "create_language_selection_keyboard",
    "create_linkable_tt_account_list_keyboard",
    "create_main_menu_keyboard",
    "create_main_settings_keyboard",
    "create_manage_muted_users_keyboard",
    "create_manage_tt_account_keyboard",
    "create_notification_settings_keyboard",
    "create_subscriber_action_menu_keyboard",
    "create_subscriber_list_keyboard",
    "create_subscription_settings_keyboard",
    "create_toggle_mute_keyboard",
    "create_user_selection_keyboard",
    "create_view_mute_list_keyboard",
]
