"""This package contains custom Aiogram middlewares."""
# Order of imports can matter if middlewares depend on each other's injected data,
# though for simple imports like these, it's mostly for organization.

from .db_session import DbSessionMiddleware
from .i18n import I18nMiddleware
from .subscription_check import SubscriptionCheckMiddleware
from .teamtalk_connection import (
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware,
)
from .user_settings import UserSettingsMiddleware

# It's good practice to define __all__ to specify what gets imported
# when `from .middlewares import *` is used, though explicit imports are better.
__all__ = [
    "ActiveTeamTalkConnectionMiddleware",
    "DbSessionMiddleware",
    "I18nMiddleware",
    "SubscriptionCheckMiddleware",
    "TeamTalkConnectionCheckMiddleware",
    "UserSettingsMiddleware",
]
