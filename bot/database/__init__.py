"""Initialize the database module and export key components."""

from .crud import (
    add_admin,
    add_subscriber,
    add_to_ban_list,
    create_deeplink,
    db_add_generic,
    db_remove_generic,
    delete_deeplink_by_token,
    get_all_admins_ids,
    get_all_subscribers_ids,
    get_ban_entries_for_telegram_id,
    get_ban_entries_for_teamtalk_username,
    get_deeplink,
    is_teamtalk_username_banned,
    is_telegram_id_banned,
    remove_admin_db,
    remove_from_ban_list_by_id,
    Admin,  # Added Admin here
)
from .engine import AsyncSessionFactoryType, create_session_factory

__all__ = [
    "create_session_factory",
    "AsyncSessionFactoryType",
    "add_subscriber",
    "get_all_subscribers_ids",
    "add_admin",
    "remove_admin_db",
    "get_all_admins_ids",
    "create_deeplink",
    "get_deeplink",
    "delete_deeplink_by_token",
    "db_add_generic",
    "db_remove_generic",
    "add_to_ban_list",
    "remove_from_ban_list_by_id",
    "is_telegram_id_banned",
    "is_teamtalk_username_banned",
    "get_ban_entries_for_telegram_id",
    "get_ban_entries_for_teamtalk_username",
    "Admin",  # And here
]
