import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.localization import get_text # Not used directly here, but good for consistency
from bot.telegram_bot.filters import IsAdminFilter
from bot.telegram_bot.utils import show_user_buttons
from pytalk.instance import TeamTalkInstance # For type hint

logger = logging.getLogger(__name__)
admin_router = Router(name="admin_router")

# Apply the IsAdminFilter to all message and callback_query handlers in this router
admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())


@admin_router.message(Command("kick"))
async def kick_command_handler(
    message: Message,
    language: str, # From UserSettingsMiddleware
    tt_instance: TeamTalkInstance | None # From TeamTalkInstanceMiddleware
):
    # IsAdminFilter already applied at router level
    await show_user_buttons(message, "kick", language, tt_instance)


@admin_router.message(Command("ban"))
async def ban_command_handler(
    message: Message,
    language: str, # From UserSettingsMiddleware
    tt_instance: TeamTalkInstance | None # From TeamTalkInstanceMiddleware
):
    # IsAdminFilter already applied at router level
    await show_user_buttons(message, "ban", language, tt_instance)
