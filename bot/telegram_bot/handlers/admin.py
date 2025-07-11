"""Telegram bot command handlers for administrator actions."""

import gettext
import logging
from typing import TYPE_CHECKING, cast

# Removed: from aiogram import Bot as AiogramBot
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

# Import SQLModel's AsyncSession for casting
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from bot.core.enums import AdminAction
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.keyboards import create_user_selection_keyboard
from bot.telegram_bot.middlewares.admin_check import AdminCheckMiddleware
from bot.telegram_bot.middlewares.teamtalk_connection import TeamTalkConnectionCheckMiddleware

from .callback_handlers.list_utils import _show_subscriber_list_page

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")
admin_router.message.middleware(AdminCheckMiddleware())
# ActiveTeamTalkConnectionMiddleware is assumed to be on a parent router.
# TeamTalkConnectionCheckMiddleware will check the tt_connection provided.
admin_router.message.middleware(TeamTalkConnectionCheckMiddleware())


async def _show_user_buttons(
    message: Message,
    command_type: AdminAction,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by parent MW; checked by local MW
) -> None:
    _ = translator.gettext
    # The tt_connection is now guaranteed to be non-None and ready by the TeamTalkConnectionCheckMiddleware.
    # Also, user is guaranteed to be an admin by AdminCheckMiddleware.
    # However, tt_connection can still be None if ActiveTeamTalkConnectionMiddleware fails to provide one,
    # but TeamTalkConnectionCheckMiddleware should then prevent handler execution.
    # For type safety, we might still check, or rely on middleware guarantees.
    # Given the middleware setup, tt_connection here should be a valid, ready connection.

    # TeamTalkConnectionCheckMiddleware ensures tt_connection, tt_connection.instance,
    # and tt_connection.online_users_cache are valid and ready.
    # Therefore, tt_connection and tt_connection.instance are not None here.
    tt_instance = tt_connection.instance  # type: ignore[union-attr] # tt_connection is not None
    my_user_id = tt_instance.getMyUserID() # type: ignore[union-attr] # tt_instance is not None

    if my_user_id is None:
        logger.error(
            "[%s] Could not get own user ID in _show_user_buttons.",
            tt_connection.server_info.host,  # type: ignore[union-attr] # tt_connection is not None
        )
        await message.reply(_("An error occurred. Please try again later."))
        return

    # online_users_cache is guaranteed by middleware and its own initialization.
    online_users = list(tt_connection.online_users_cache.values())  # type: ignore[union-attr] # tt_connection is not None

    if not online_users:
        await message.reply(
            _("No users found online on server {server_host}.").format(
                server_host=tt_connection.server_info.host  # type: ignore[union-attr]
            )
        )
        return

    sorted_users = sorted(online_users, key=lambda u: get_tt_user_display_name(u, translator).lower())
    builder = await create_user_selection_keyboard(translator, sorted_users, command_type)

    command_text_map = {
        AdminAction.KICK: _("Select a user to kick from {server_host}:").format(
            server_host=tt_connection.server_info.host  # type: ignore[union-attr]
        ),
        AdminAction.BAN: _("Select a user to ban from {server_host}:").format(
            server_host=tt_connection.server_info.host  # type: ignore[union-attr]
        ),
    }
    reply_text = command_text_map.get(command_type, _("Select a user:"))

    await message.reply(reply_text, reply_markup=builder.as_markup())


@admin_router.message(Command("kick"))
async def kick_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
) -> None:
    """Handles the /kick command for administrators."""
    await _show_user_buttons(message, AdminAction.KICK, translator, tt_connection)


@admin_router.message(Command("ban"))
async def ban_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
) -> None:
    """Handles the /ban command for administrators."""
    await _show_user_buttons(message, AdminAction.BAN, translator, tt_connection)


@admin_router.message(Command("subscribers"))
async def subscribers_command_handler(
    message: Message,
    session: AsyncSession,  # Injected by DbSessionMiddleware
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
) -> None:
    """Handles the /subscribers command for administrators."""
    await _show_subscriber_list_page(
        message, cast(SQLModelAsyncSession, session), services.bot_event, translator, page=0
    )
