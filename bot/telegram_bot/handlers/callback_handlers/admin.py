"""Callback query handlers for admin actions from inline keyboards."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import AdminCommand
from bot.services.moderation_service import ModerationService
from bot.telegram_bot.callback_data import AdminCallback
from bot.telegram_bot.handlers.decorators import (
    ensure_message_context,
)
from bot.telegram_bot.ui_utils import edit_message_text

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
    moderation_service: Annotated[ModerationService, FromDishka()],
) -> None:
    """Processes admin actions (kick/ban) selected from an inline keyboard."""
    _ = translator.gettext

    if callback_data.action == AdminCommand.KICK:
        moderation_result = await moderation_service.kick_user_from_server(
            user_id=callback_data.user_id,
            admin_telegram_id=callback_query.from_user.id,
            translator=translator,
        )
    elif callback_data.action == AdminCommand.BAN:
        moderation_result = await moderation_service.ban_user_from_server(
            user_id=callback_data.user_id,
            admin_telegram_id=callback_query.from_user.id,
            translator=translator,
        )

    await callback_query.answer(
        text=moderation_result.message_key,
        show_alert=not moderation_result.success,
    )

    if moderation_result.success and callback_query.message:
        await edit_message_text(
            message_to_edit=callback_query.message,
            text=moderation_result.message_key,
            reply_markup=None,
        )
