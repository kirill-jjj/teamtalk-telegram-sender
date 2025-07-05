import logging
import gettext
from aiogram import Router, F, Bot as AiogramBot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from bot.teamtalk_bot.connection import TeamTalkConnection

# Импортируем бизнес-логику напрямую, а не через хендлеры
from bot.telegram_bot.handlers.admin import _show_user_buttons
from bot.telegram_bot.handlers.callback_handlers.list_utils import _show_subscriber_list_page
from bot.telegram_bot.handlers.user import who_command_handler, help_command_handler, settings_command_handler
from bot.telegram_bot.handlers.callback_handlers._helpers import ensure_message_context

from bot.telegram_bot.callback_data import MenuCallback
from bot.core.enums import AdminAction

# Для типизации
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")


# --- Хендлеры обычных пользователей ---

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application",
    tt_connection: TeamTalkConnection | None
):
    await who_command_handler(
        message=query.message,
        translator=translator,
        app=app,
        tt_connection=tt_connection
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
@ensure_message_context
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application"
):
    await help_command_handler(
        message=query.message,
        _=translator.gettext,
        app=app
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
@ensure_message_context
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application"
):
    await settings_command_handler(
        message=query.message,
        _=translator.gettext,
        app=app
    )
    await query.answer()


# --- Хендлеры администратора ---

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application",
    tt_connection: TeamTalkConnection | None
):
    # Правильная проверка прав пользователя, нажавшего на кнопку
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(translator.gettext("You are not authorized to perform this action."), show_alert=True)
        return

    # Прямой вызов нужной функции
    await _show_user_buttons(query.message, AdminAction.KICK, translator.gettext, tt_connection)
    await query.answer()


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application",
    tt_connection: TeamTalkConnection | None
):
    # Правильная проверка прав пользователя, нажавшего на кнопку
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(translator.gettext("You are not authorized to perform this action."), show_alert=True)
        return

    # Прямой вызов нужной функции
    await _show_user_buttons(query.message, AdminAction.BAN, translator.gettext, tt_connection)
    await query.answer()


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    session: AsyncSession,
    bot: AiogramBot,
    translator: "gettext.GNUTranslations",
    app: "Application"
):
    # Правильная проверка прав пользователя, нажавшего на кнопку
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(translator.gettext("You are not authorized to perform this action."), show_alert=True)
        return

    # Прямой вызов нужной функции
    await _show_subscriber_list_page(query.message, session, bot, translator.gettext, page=0)
    await query.answer()
