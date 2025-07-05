# bot/telegram_bot/commands.py

import logging
from typing import List, Callable
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)

# Функции, которые возвращают локализованные списки BotCommand
def get_user_commands(_: Callable[[str], str]) -> List[BotCommand]:
    """Возвращает список объектов BotCommand для обычных пользователей, локализованный."""
    return [
        BotCommand(command="menu", description=_("Show main menu with all commands")),
        BotCommand(command="who", description=_("Show online users in TeamTalk")),
        BotCommand(command="help", description=_("Show this help message")),
        BotCommand(command="settings", description=_("Access interactive settings menu")),
    ]

def get_admin_commands(_: Callable[[str], str]) -> List[BotCommand]:
    """Возвращает список объектов BotCommand для администраторов, локализованный."""
    # Команды администратора включают команды пользователя плюс специфичные для администратора
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
    from sqlalchemy.ext.asyncio import AsyncSession # For session type hint

async def set_telegram_commands(bot: Bot, admin_ids: List[int], default_language_code: str, app: "Application", session: "AsyncSession"):
    """
    Устанавливает команды бота для пользователей по умолчанию (все приватные чаты) и для конкретных администраторов.
    Эта функция использует default_language_code для глобальных команд и пытается
    локализовать команды администратора на основе их индивидуальных настроек языка, если таковые имеются.
    """
    # Локальные импорты для избежания циклических зависимостей
    from bot.language import get_translator

    # 1. Установка команд для всех приватных чатов с использованием языка по умолчанию
    default_translator = get_translator(default_language_code)
    user_commands_default_lang = get_user_commands(default_translator.gettext)
    default_scope = BotCommandScopeAllPrivateChats()
    try:
        # Удаляем существующие команды для этой области, чтобы обеспечить чистое обновление
        await bot.delete_my_commands(scope=default_scope)
        await bot.set_my_commands(commands=user_commands_default_lang, scope=default_scope)
        logger.info(f"Успешно установлены команды пользователя по умолчанию для области {default_scope!r} на языке '{default_language_code}'.")
    except TelegramAPIError as e:
        logger.error(f"Не удалось установить/удалить команды пользователя Telegram по умолчанию для области {default_scope!r}: {e}")
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при установке/удалении команд пользователя по умолчанию: {e}")


    # 2. Установка команд для каждого чата администратора, локализованных, если возможно
    # async with SessionFactory() as session: # Session is now passed as an argument
    for admin_id in admin_ids:
        admin_lang_code = default_language_code # Fallback to default
        try:
            # Попытка получить язык из кеша, затем из БД, затем по умолчанию
            # admin_settings = USER_SETTINGS_CACHE.get(admin_id) # Use app.user_settings_cache
            admin_settings = app.user_settings_cache.get(admin_id)
            if not admin_settings:
                # Это может произойти, если кеш не полностью загружен или администратор был только что добавлен
                # Ensure get_or_create_user_settings is awaitable and session is passed
                # admin_settings_from_db = await get_or_create_user_settings(admin_id, session) # Use app.get_or_create_user_settings
                admin_settings_from_db = await app.get_or_create_user_settings(admin_id, session)
                if admin_settings_from_db:
                     admin_settings = admin_settings_from_db
                     # USER_SETTINGS_CACHE[admin_id] = admin_settings_from_db # Update cache via app if needed, get_or_create should handle it
                     app.user_settings_cache[admin_id] = admin_settings_from_db


            # Используем язык из настроек администратора или язык по умолчанию из конфигурации
            if admin_settings and admin_settings.language_code:
                admin_lang_code = admin_settings.language_code
            else:
                # If still no specific language, use the app's default language
                # admin_lang_code = app_config.DEFAULT_LANG # Use app.app_config.DEFAULT_LANG
                admin_lang_code = app.app_config.DEFAULT_LANG


            admin_translator = get_translator(admin_lang_code)
            admin_commands_localized = get_admin_commands(admin_translator.gettext)
            admin_scope = BotCommandScopeChat(chat_id=admin_id)

            await bot.delete_my_commands(scope=admin_scope) # Delete old commands first
            await bot.set_my_commands(commands=admin_commands_localized, scope=admin_scope)
            logger.info(f"Успешно установлены команды администратора для admin_id {admin_id} в области {admin_scope!r} (язык: {admin_lang_code}).")
        except TelegramAPIError as e:
            logger.error(f"Не удалось установить команды администратора Telegram для admin_id {admin_id}, области {admin_scope!r}: {e}")
        except Exception as e:
                logger.error(f"Произошла непредвиденная ошибка при установке команд администратора для admin_id {admin_id}: {e}", exc_info=True)

async def clear_telegram_commands_for_chat(bot: Bot, chat_id: int):
    """Очищает все пользовательские команды для конкретного чата."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info(f"Успешно очищены команды для chat_id {chat_id}.")
    except TelegramAPIError as e:
        logger.error(f"Не удалось очистить команды для chat_id {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при очистке команд для chat_id {chat_id}: {e}")
