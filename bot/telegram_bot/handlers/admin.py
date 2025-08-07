"""Telegram bot command handlers for administrator actions."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import AdminCommand
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.filters.admin import IsAdmin
from bot.telegram_bot.keyboards import create_user_selection_keyboard
from bot.telegram_bot.types.bots import EventBot

from .callback_handlers.list_utils import (
    _show_banned_list_page,
    _show_subscriber_list_page,
)

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")


async def _show_user_buttons(
    message: Message,
    command_type: AdminCommand,
    translator: NullTranslations,
    tt_connection: TeamTalkConnection,
) -> None:
    _ = translator.gettext
    tt_instance = tt_connection.instance
    if not tt_instance:
        logger.error(
            "[%s] Could not get own user ID in _show_user_buttons: tt_instance is None.",
            tt_connection.server_info.host,
        )
        await message.reply(_("An error occurred. Please try again later."))
        return
    my_user_id = tt_instance.getMyUserID()

    if my_user_id is None:
        logger.error(
            "[%s] Could not get own user ID in _show_user_buttons.",
            tt_connection.server_info.host,
        )
        await message.reply(_("An error occurred. Please try again later."))
        return

    online_users = list(tt_connection.online_users_cache.values())

    if not online_users:
        await message.reply(
            _("No users found online on server {server_host}.").format(
                server_host=tt_connection.server_info.host
            )
        )
        return

    sorted_users = sorted(
        online_users, key=lambda u: get_tt_user_display_name(u, translator).lower()
    )
    builder = await create_user_selection_keyboard(
        translator, sorted_users, command_type
    )

    command_text_map = {
        AdminCommand.KICK: _("Select a user to kick from {server_host}:").format(
            server_host=tt_connection.server_info.host
        ),
        AdminCommand.BAN: _("Select a user to ban from {server_host}:").format(
            server_host=tt_connection.server_info.host
        ),
    }
    reply_text = command_text_map.get(command_type, _("Select a user:"))

    await message.reply(reply_text, reply_markup=builder.as_markup())


@admin_router.message(Command("kick"), IsAdmin())
async def on_kick_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    tt_connection: Annotated[TeamTalkConnection | None, FromDishka()],
) -> None:
    """Handles the /kick command for administrators."""
    if not tt_connection:
        _ = translator.gettext
        await message.reply(_("TeamTalk connection is not active."))
        return
    await _show_user_buttons(message, AdminCommand.KICK, translator, tt_connection)


@admin_router.message(Command("ban"), IsAdmin())
async def on_ban_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    tt_connection: Annotated[TeamTalkConnection | None, FromDishka()],
) -> None:
    """Handles the /ban command for administrators."""
    if not tt_connection:
        _ = translator.gettext
        await message.reply(_("TeamTalk connection is not active."))
        return
    await _show_user_buttons(message, AdminCommand.BAN, translator, tt_connection)


@admin_router.message(Command("subscribers"), IsAdmin())
async def on_subscribers_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    user_repo: Annotated[UserRepository, FromDishka()],
    subscriber_repo: Annotated[SubscriberRepository, FromDishka()],
) -> None:
    """Handles the /subscribers command for administrators."""
    await _show_subscriber_list_page(
        target=message,
        user_repo=user_repo,
        subscriber_repo=subscriber_repo,
        bot=bot,
        translator=translator,
        page=0,
    )


@admin_router.message(Command("unban"), IsAdmin())
async def on_unban_command(
    message: Message,
    translator: Annotated[NullTranslations, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    ban_repo: Annotated[BanRepository, FromDishka()],
) -> None:
    """Handles the /unban command for administrators."""
    await _show_banned_list_page(
        target=message,
        ban_repo=ban_repo,
        bot=bot,
        page=0,
        translator=translator,
    )
