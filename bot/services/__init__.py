"""Services layer for the bot.

This package groups modules that encapsulate specific business logic
or interactions with external services (like the TeamTalk server API, database etc.),
but are not directly part of the Telegram or TeamTalk bot handlers/commands.
"""

from . import deeplink_service, notification_service, user_service
from .deeplink_service import (
    process_deeplink,
    process_subscribe_deeplink,
    process_unsubscribe_deeplink,
)
from .notification_service import (
    filter_recipients_for_noon,
    is_linked_user_online,
    is_user_subject_to_noon_check,
)
from .user_service import (
    delete_full_user_profile,
)

__all__ = [
    # Modules (for direct service.module usage if preferred)
    "deeplink_service",
    # User service functions
    "delete_full_user_profile",
    "process_deeplink",  # Deeplink service functions
    "filter_recipients_for_noon",  # Notification service functions
    "is_linked_user_online",  # Notification service functions
    "is_user_subject_to_noon_check",  # Notification service functions
    "notification_service",
    "process_subscribe_deeplink",  # Deeplink service functions
    "process_unsubscribe_deeplink",  # Deeplink service functions
    "user_service",
]
