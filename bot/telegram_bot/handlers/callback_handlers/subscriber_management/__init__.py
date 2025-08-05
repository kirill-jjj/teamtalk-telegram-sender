"""A package for handlers related to admin management of subscribers."""

from aiogram import Router

from .actions import actions_router
from .settings import settings_router
from .tt_account import tt_account_router

subscriber_management_router = Router(name="subscriber_management")
subscriber_management_router.include_routers(
    actions_router,
    settings_router,
    tt_account_router,
)

__all__ = ["subscriber_management_router"]
