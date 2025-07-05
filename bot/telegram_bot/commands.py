# bot/telegram_bot/commands.py

import logging
from typing import List, Callable
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)

# Functions that return localized lists of BotCommand
def get_user_commands(_: Callable[[str], str]) -> List[BotCommand]:
    """Returns a list of BotCommand objects for regular users, localized."""
    return [
        BotCommand(command="menu", description=_("Show main menu with all commands")),
        BotCommand(command="who", description=_("Show online users in TeamTalk")),
        BotCommand(command="help", description=_("Show this help message")),
        BotCommand(command="settings", description=_("Access interactive settings menu")),
    ]

def get_admin_commands(_: Callable[[str], str]) -> List[BotCommand]:
    """Returns a list of BotCommand objects for administrators, localized."""
    # Administrator commands include user commands plus administrator-specific ones
    admin_specific = [
        BotCommand(command="kick", description=_("Kick TT user (admin, via buttons)")),
        BotCommand(command="ban", description=_("Ban TT user (admin, via buttons)")),
        BotCommand(command="subscribers", description=_("View and manage subscribed users")),
    ]
    return get_user_commands(_) + admin_specific

# Add TYPE_CHECKING and Application import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Функции get_user_commands и get_admin_commands остаются без изменений.
# (Они были предоставлены в предыдущем сообщении и здесь предполагается, что они уже есть)

async def set_telegram_commands(app: "Application"):
    """
    Sets bot commands globally for all supported languages and individually for administrators.
    """
    logger.info("Setting up global and admin-specific Telegram commands...")

    # --- 1. Установка глобальных команд для каждого поддерживаемого языка ---
    # Это команды, которые увидят все обычные пользователи.
    for lang_info in app.available_languages:
        lang_code = lang_info["code"]
        translator = app.get_translator(lang_code)
        user_commands = get_user_commands(translator.gettext)

        try:
            # Устанавливаем команды для всех пользователей с этим языком в клиенте Telegram
            await app.tg_bot_event.set_my_commands(
                commands=user_commands,
                scope=BotCommandScopeAllPrivateChats(),
                language_code=lang_code if lang_code != app.app_config.DEFAULT_LANG else None
                # Для языка по умолчанию language_code=None
            )
            logger.info(f"Successfully set global user commands for language: '{lang_code}'.")
        except TelegramAPIError as e:
            logger.error(f"Failed to set global commands for language '{lang_code}': {e}")

    # --- 2. Установка индивидуальных команд для каждого администратора ---
    # Это переопределит глобальные команды для конкретных пользователей-админов.
    # Их команды будут на том языке, который они выбрали в настройках бота.
    async with app.session_factory() as session:
        for admin_id in app.admin_ids_cache:
            admin_lang_code = app.app_config.DEFAULT_LANG # Язык по умолчанию

            # Получаем язык админа из кеша или БД
            admin_settings = app.user_settings_cache.get(admin_id)
            if not admin_settings:
                admin_settings = await app.get_or_create_user_settings(admin_id, session)

            if admin_settings and admin_settings.language_code:
                admin_lang_code = admin_settings.language_code

            admin_translator = app.get_translator(admin_lang_code)
            admin_commands = get_admin_commands(admin_translator.gettext)
            admin_scope = BotCommandScopeChat(chat_id=admin_id)

            try:
                # Устанавливаем персональный набор команд для администратора
                # Нет необходимости удалять команды перед установкой, set_my_commands перезаписывает.
                await app.tg_bot_event.set_my_commands(commands=admin_commands, scope=admin_scope)
                logger.info(f"Successfully set custom commands for admin {admin_id} in language '{admin_lang_code}'.")
            except TelegramAPIError as e:
                logger.error(f"Failed to set commands for admin {admin_id}: {e}")

async def clear_telegram_commands_for_chat(bot: Bot, chat_id: int):
    """Clears all custom commands for a specific chat."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info(f"Successfully cleared commands for chat_id {chat_id}.")
    except TelegramAPIError as e:
        logger.error(f"Failed to clear commands for chat_id {chat_id}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while clearing commands for chat_id {chat_id}: {e}")
