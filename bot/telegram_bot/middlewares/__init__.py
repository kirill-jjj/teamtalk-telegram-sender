"""
This package contains custom Aiogram middlewares.
"""
# Order of imports can matter if middlewares depend on each other's injected data,
# though for simple imports like these, it's mostly for organization.

from .application import ApplicationMiddleware
from .db_session import DbSessionMiddleware
from .subscription_check import SubscriptionCheckMiddleware
from .user_settings import UserSettingsMiddleware
from .teamtalk_connection import (
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware,
)
from .admin_check import AdminCheckMiddleware

# It's good practice to define __all__ to specify what gets imported
# when `from .middlewares import *` is used, though explicit imports are better.
__all__ = [
    "ApplicationMiddleware",
    "DbSessionMiddleware",
    "SubscriptionCheckMiddleware",
    "UserSettingsMiddleware",
    "ActiveTeamTalkConnectionMiddleware",
    "TeamTalkConnectionCheckMiddleware",
    "AdminCheckMiddleware",
]
