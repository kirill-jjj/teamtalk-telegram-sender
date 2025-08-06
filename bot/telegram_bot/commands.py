"""Functions for setting and managing Telegram bot commands."""

from collections.abc import Callable
from gettext import GNUTranslations, NullTranslations
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.services.cache_service import CacheService

logger = logging.getLogger(__name__)


def get_user_commands(_: Callable[[str], str]) -> list[BotCommand]:
    """Returns a list of BotCommand objects for regular users, localized."""
    return [
        BotCommand(command="menu", description=_("Show main menu with all commands")),
        BotCommand(command="who", description=_("Show online users in TeamTalk")),
        BotCommand(command="help", description=_("Show this help message")),
        BotCommand(command="settings", description=_("Access interactive settings menu")),
    ]


def get_admin_commands(_: Callable[[str], str]) -> list[BotCommand]:
    """Returns a list of BotCommand objects for administrators, localized."""
    admin_specific = [
        BotCommand(command="kick", description=_("Kick TT user (admin, via buttons)")),
        BotCommand(command="ban", description=_("Ban TT user (admin, via buttons)")),
        BotCommand(command="unban", description=_("Unban user (shows a list of banned users)")),
        BotCommand(command="subscribers", description=_("View and manage subscribed users")),
    ]
    return get_user_commands(_) + admin_specific


async def set_telegram_commands(
    bot: Bot,
    cache: CacheService,
    translator_factory: Callable[[str], GNUTranslations | NullTranslations],
    available_languages: list[LanguageInfo],
    settings: Settings,
) -> None:
    """Sets bot commands globally for all supported languages and individually for administrators."""
    logger.info("Setting up global and admin-specific Telegram commands...")

    for lang_info in available_languages:
        lang_code = lang_info["code"]
        translator = translator_factory(lang_code)
        user_commands = get_user_commands(translator.gettext)

        try:
            await bot.set_my_commands(
                commands=user_commands,
                scope=BotCommandScopeAllPrivateChats(),
                language_code=lang_code if lang_code != settings.general.default_lang else None,
            )
            logger.info("Successfully set global user commands for language: '%s'.", lang_code)
        except TelegramAPIError:
            logger.exception("Failed to set global commands for language '%s'.", lang_code)

    for admin_id in cache.get_all_admin_ids():
        admin_lang_code = settings.general.default_lang
        admin_settings = cache.get_user_settings(admin_id)
        if admin_settings and admin_settings.language_code:
            admin_lang_code = admin_settings.language_code

        admin_translator = translator_factory(admin_lang_code)
        admin_commands = get_admin_commands(admin_translator.gettext)
        admin_scope = BotCommandScopeChat(chat_id=admin_id)

        try:
            await bot.set_my_commands(
                commands=admin_commands,
                scope=admin_scope,
                language_code=admin_lang_code if admin_lang_code != settings.general.default_lang else None,
            )
            logger.info("Successfully set custom commands for admin %s in language '%s'.", admin_id, admin_lang_code)
        except TelegramAPIError:
            logger.exception("Failed to set commands for admin %s (lang: %s).", admin_id, admin_lang_code)


async def clear_telegram_commands_for_chat(bot: Bot, chat_id: int) -> None:
    """Clears all custom commands for a specific chat."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info("Successfully cleared commands for chat_id %s.", chat_id)
    except TelegramAPIError:
        logger.exception("Failed to clear commands for chat_id %s.", chat_id)
    except Exception:
        logger.exception("An unexpected error occurred while clearing commands for chat_id %s.", chat_id)
