"""Functions for setting and managing Telegram bot commands."""

from collections.abc import Callable
import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

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
        BotCommand(command="subscribers", description=_("View and manage subscribed users")),
    ]
    return get_user_commands(_) + admin_specific


if TYPE_CHECKING:
    from bot.services_container import Services


async def set_telegram_commands(services: "Services"):
    """Sets bot commands globally for all supported languages and individually for administrators."""
    logger.info("Setting up global and admin-specific Telegram commands...")

    # --- 1. Set global commands for each supported language ---
    for lang_info in services.available_languages:
        lang_code = lang_info["code"]
        translator = services.get_translator(lang_code)
        user_commands = get_user_commands(translator.gettext)

        try:
            await services.bot_event.set_my_commands(
                commands=user_commands,
                scope=BotCommandScopeAllPrivateChats(),
                language_code=lang_code if lang_code != services.config.general.default_lang else None,
            )
            logger.info("Successfully set global user commands for language: '%s'.", lang_code)
        except TelegramAPIError as e:
            logger.error("Failed to set global commands for language '%s': %s", lang_code, e)

    # --- 2. Set individual commands for each administrator ---
    async with services.session_factory() as session:
        for admin_id in services.cache.get_all_admin_ids():
            admin_lang_code = services.config.general.default_lang

            admin_settings = services.cache.get_user_settings(admin_id)
            if not admin_settings:
                admin_settings = await services.get_or_create_user_settings(admin_id, session)

            if admin_settings and admin_settings.language_code:
                admin_lang_code = admin_settings.language_code

            admin_translator = services.get_translator(admin_lang_code)
            admin_commands = get_admin_commands(admin_translator.gettext)
            admin_scope = BotCommandScopeChat(chat_id=admin_id)

            try:
                await services.bot_event.set_my_commands(
                    commands=admin_commands,
                    scope=admin_scope,
                    language_code=admin_lang_code if admin_lang_code != services.config.general.default_lang else None,
                )
                logger.info(
                    "Successfully set custom commands for admin %s in language '%s'.", admin_id, admin_lang_code
                )
            except TelegramAPIError as e:
                logger.error(
                    "Failed to set commands for admin %s (lang: %s): %s", admin_id, admin_lang_code, e
                )


async def clear_telegram_commands_for_chat(bot: Bot, chat_id: int):
    """Clears all custom commands for a specific chat."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info("Successfully cleared commands for chat_id %s.", chat_id)
    except TelegramAPIError as e:
        logger.error("Failed to clear commands for chat_id %s: %s", chat_id, e)
    except Exception as e:
        logger.error("An unexpected error occurred while clearing commands for chat_id %s: %s", chat_id, e)
