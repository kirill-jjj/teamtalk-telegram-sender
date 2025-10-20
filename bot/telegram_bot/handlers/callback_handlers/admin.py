"""Callback query handlers for admin actions from inline keyboards."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.commands import BanUserCommand, KickUserCommand, ModerationResult
from bot.core.enums import AdminCommand
from bot.telegram_bot.callback_data import AdminCallback
from bot.telegram_bot.handlers.decorators import (
    ensure_message_context,
)
from bot.telegram_bot.ui_utils import safe_edit_text

logger = logging.getLogger(__name__)
admin_actions_router = Router(name="callback_handlers.admin")


@admin_actions_router.callback_query(
    AdminCallback.filter(F.action.in_({AdminCommand.KICK, AdminCommand.BAN}))
)
@ensure_message_context
async def on_moderation_confirm(
    callback_query: CallbackQuery,
    callback_data: AdminCallback,
    translator: Annotated[NullTranslations, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
) -> None:
    """Processes admin actions (kick/ban) selected from an inline keyboard."""
    _ = translator.gettext

    command: KickUserCommand | BanUserCommand
    lang_code = translator.info().get("language", "en")
    if callback_data.action == AdminCommand.KICK:
        command = KickUserCommand(
            user_id=callback_data.user_id,
            admin_telegram_id=callback_query.from_user.id,
            lang_code=lang_code,
        )
    elif callback_data.action == AdminCommand.BAN:
        command = BanUserCommand(
            user_id=callback_data.user_id,
            admin_telegram_id=callback_query.from_user.id,
            lang_code=lang_code,
        )
    else:
        # This case should not be reached if the filter is correct
        await callback_query.answer(_("Unknown action."), show_alert=True)
        return

    result: ModerationResult = await command_bus.execute(command)

    await callback_query.answer(text=result.message, show_alert=not result.success)

    if result.success and callback_query.message:
        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=result.message,
            reply_markup=None,
        )
