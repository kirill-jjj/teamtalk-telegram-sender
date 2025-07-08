"""Services layer for the bot.

This package groups modules that encapsulate specific business logic
or interactions with external services (like the TeamTalk server API, database etc.),
but are not directly part of the Telegram or TeamTalk bot handlers/commands.
"""

from . import deeplink_service
from . import user_service
from . import notification_service

from .deeplink_service import (
    process_subscribe_deeplink,
    process_unsubscribe_deeplink,
    execute_deeplink_action,
)

from .user_service import (
    get_user_settings_from_db_or_default,
    update_user_settings_in_db,
    delete_full_user_profile,
    create_or_update_user_from_telegram_data,
    get_user_language_code,
    get_user_settings_from_cache_or_db,
)

from .notification_service import (
    is_user_subject_to_noon_check,
    is_linked_user_online,
    filter_recipients_for_noon,
)


__all__ = [
    # Modules (for direct service.module usage if preferred)
    "deeplink_service",
    "user_service",
    "notification_service",
    # Deeplink service functions
    "process_subscribe_deeplink",
    "process_unsubscribe_deeplink",
    "execute_deeplink_action",
    # User service functions
    "get_user_settings_from_db_or_default",
    "update_user_settings_in_db",
    "delete_full_user_profile",
    "create_or_update_user_from_telegram_data",
    "get_user_language_code",
    "get_user_settings_from_cache_or_db",
    # Notification service functions
    "is_user_subject_to_noon_check",
    "is_linked_user_online",
    "filter_recipients_for_noon",
]
