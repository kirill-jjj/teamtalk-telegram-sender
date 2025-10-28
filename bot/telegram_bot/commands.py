"""Functions for setting and managing Telegram bot commands."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from bot.config import Settings
from bot.core.languages import LanguageInfo
from bot.services.cache_service import CacheService
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)


def get_user_commands(_: Callable[[str], str]) -> list[BotCommand]:
    """Returns a list of BotCommand objects for regular users, localized."""
    return [
        BotCommand(command="menu", description=_("Show main menu with all commands")),
        BotCommand(command="who", description=_("Show online users in TeamTalk")),
        BotCommand(command="help", description=_("Show this help message")),
        BotCommand(
            command="settings", description=_("Access interactive settings menu")
        ),
    ]


def get_admin_commands(_: Callable[[str], str]) -> list[BotCommand]:
    """Returns a list of BotCommand objects for administrators, localized."""
    admin_specific = [
        BotCommand(command="kick", description=_("Kick TT user (admin, via buttons)")),
        BotCommand(command="ban", description=_("Ban TT user (admin, via buttons)")),
        BotCommand(
            command="unban", description=_("Unban user (shows a list of banned users)")
        ),
        BotCommand(
            command="subscribers", description=_("View and manage subscribed users")
        ),
    ]
    return get_user_commands(_) + admin_specific


async def set_telegram_commands(
    bot: EventBot,
    cache: CacheService,
    translator_factory: Callable[[str], NullTranslations],
    available_languages: list[LanguageInfo],
    settings: Settings,
) -> None:
    """Set bot commands globally for all languages and individually for admins."""
    logger.debug("Setting up global and admin-specific Telegram commands...")

    global_command_tasks = []
    for lang_info in available_languages:
        lang_code = lang_info["code"]
        translator = translator_factory(lang_code)
        user_commands = get_user_commands(translator.gettext)

        global_command_tasks.append(
            bot.set_my_commands(
                commands=user_commands,
                scope=BotCommandScopeAllPrivateChats(),
                language_code=lang_code
                if lang_code != settings.general.default_lang
                else None,
            )
        )

    try:
        await asyncio.gather(*global_command_tasks)
        logger.debug("Successfully set global user commands for all languages.")
    except TelegramAPIError:
        logger.exception("Failed to set global commands for one or more languages.")

    admin_command_tasks = []
    for admin_id in cache.get_all_admin_ids():
        admin_lang_code = settings.general.default_lang
        admin_settings = cache.get_user_settings(admin_id)
        if admin_settings and admin_settings.language_code:
            admin_lang_code = admin_settings.language_code

        admin_translator = translator_factory(admin_lang_code)
        admin_commands = get_admin_commands(admin_translator.gettext)
        admin_scope = BotCommandScopeChat(chat_id=admin_id)

        admin_command_tasks.append(
            bot.set_my_commands(
                commands=admin_commands,
                scope=admin_scope,
                language_code=admin_lang_code
                if admin_lang_code != settings.general.default_lang
                else None,
            )
        )

    try:
        await asyncio.gather(*admin_command_tasks)
        logger.debug("Successfully set custom commands for all admins.")
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            logger.warning(
                "Could not set commands for one or more admins: chat not found. "
                "This is expected if the admin has not started the bot yet."
            )
        else:
            logger.exception("TelegramBadRequest while setting commands for admins.")
    except TelegramAPIError:
        logger.exception("Failed to set commands for one or more admins.")


async def clear_telegram_commands_for_chat(bot: EventBot, chat_id: int) -> None:
    """Clears all custom commands for a specific chat."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info("Successfully cleared commands for chat_id %s.", chat_id)
    except TelegramAPIError:
        logger.exception("Failed to clear commands for chat_id %s.", chat_id)
    except (RuntimeError, TypeError):
        logger.exception(
            "An unexpected error occurred while clearing commands for chat_id %s.",
            chat_id,
        )


async def update_user_bot_commands(
    telegram_id: int,
    new_lang_code: str,
    cache: CacheService,
    bot: EventBot,
    translator: NullTranslations,
) -> bool:
    """Update the bot commands for a user based on their admin status and language."""
    _ = translator.gettext
    is_admin = cache.is_admin(telegram_id)
    commands: list[BotCommand] = (
        get_admin_commands(_) if is_admin else get_user_commands(_)
    )

    scope = BotCommandScopeChat(chat_id=telegram_id)
    try:
        await bot.set_my_commands(
            commands=commands, scope=scope, language_code=new_lang_code
        )
        logger.debug(
            "Successfully updated commands for user %s (admin: %s) in language '%s'.",
            telegram_id,
            is_admin,
            new_lang_code,
        )
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            logger.warning(
                "Could not set commands for user %s (admin: %s): "
                "chat not found. This is expected if the user hasn't "
                "started the bot.",
                telegram_id,
                is_admin,
            )
        else:
            logger.exception(
                "TelegramBadRequest while updating commands for user %s (admin: %s).",
                telegram_id,
                is_admin,
            )
        return False
    except TelegramAPIError:
        logger.exception(
            "Failed to update commands for user %s (admin: %s) in language '%s'.",
            telegram_id,
            is_admin,
            new_lang_code,
        )
        return False
    else:
        return True
