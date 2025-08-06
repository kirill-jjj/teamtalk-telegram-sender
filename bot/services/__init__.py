"""Services layer for the bot.

This package groups modules that encapsulate specific business logic
or interactions with external services (like the TeamTalk server API, database etc.),
but are not directly part of the Telegram or TeamTalk bot handlers/commands.
"""

from . import deeplink_service, notification_service, user_service
from .deeplink_service import (
    execute_deeplink,
    execute_subscribe_deeplink,
    execute_unsubscribe_deeplink,
)
from .notification_service import (
    is_linked_user_online,
    is_user_subject_to_noon_check,
)
from .user_service import (
    delete_user_profile,
)

__all__ = [
    "deeplink_service",
    "delete_user_profile",
    "execute_deeplink",
    "execute_subscribe_deeplink",
    "execute_unsubscribe_deeplink",
    "is_linked_user_online",
    "is_user_subject_to_noon_check",
    "notification_service",
    "user_service",
]
