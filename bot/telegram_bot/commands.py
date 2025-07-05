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
    from sqlalchemy.ext.asyncio import AsyncSession # For session type hint

async def set_telegram_commands(bot: Bot, admin_ids: List[int], default_language_code: str, app: "Application", session: "AsyncSession"):
    """
    Sets bot commands for default users (all private chats) and for specific administrators.
    This function uses default_language_code for global commands and attempts to
    localize administrator commands based on their individual language settings, if available.
    """
    # 1. Set commands for all private chats using the default language
    default_translator = app.get_translator(default_language_code)
    user_commands_default_lang = get_user_commands(default_translator.gettext)
    default_scope = BotCommandScopeAllPrivateChats()
    try:
        # Delete existing commands for this scope to ensure a clean update
        await bot.delete_my_commands(scope=default_scope)
        await bot.set_my_commands(commands=user_commands_default_lang, scope=default_scope)
        logger.info(f"Successfully set default user commands for scope {default_scope!r} in '{default_language_code}' language.")
    except TelegramAPIError as e:
        logger.error(f"Failed to set/delete default Telegram user commands for scope {default_scope!r}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while setting/deleting default user commands: {e}")


    # 2. Set commands for each administrator's chat, localized if possible
    for admin_id in admin_ids:
        admin_lang_code = default_language_code # Fallback to default
        try:
            # Attempt to get language from cache, then DB, then default
            admin_settings = app.user_settings_cache.get(admin_id)
            if not admin_settings:
                # This can happen if the cache is not fully loaded or the admin was just added
                admin_settings_from_db = await app.get_or_create_user_settings(admin_id, session)
                if admin_settings_from_db:
                     admin_settings = admin_settings_from_db
                     # Update app cache directly, get_or_create_user_settings might not update the app's cache instance
                     app.user_settings_cache[admin_id] = admin_settings_from_db


            # Use language from admin settings or default language from config
            if admin_settings and admin_settings.language_code:
                admin_lang_code = admin_settings.language_code
            else:
                # If still no specific language, use the app's default language
                admin_lang_code = app.app_config.DEFAULT_LANG


            admin_translator = app.get_translator(admin_lang_code)
            admin_commands_localized = get_admin_commands(admin_translator.gettext)
            admin_scope = BotCommandScopeChat(chat_id=admin_id)

            await bot.delete_my_commands(scope=admin_scope) # Delete old commands first
            await bot.set_my_commands(commands=admin_commands_localized, scope=admin_scope)
            logger.info(f"Successfully set admin commands for admin_id {admin_id} in scope {admin_scope!r} (language: {admin_lang_code}).")
        except TelegramAPIError as e:
            logger.error(f"Failed to set Telegram admin commands for admin_id {admin_id}, scope {admin_scope!r}: {e}")
        except Exception as e:
                logger.error(f"An unexpected error occurred while setting admin commands for admin_id {admin_id}: {e}", exc_info=True)

async def clear_telegram_commands_for_chat(bot: Bot, chat_id: int):
    """Clears all custom commands for a specific chat."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info(f"Successfully cleared commands for chat_id {chat_id}.")
    except TelegramAPIError as e:
        logger.error(f"Failed to clear commands for chat_id {chat_id}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while clearing commands for chat_id {chat_id}: {e}")
