import logging
from typing import List
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)

# Define global command lists
USER_COMMANDS: List[BotCommand] = [
    BotCommand(command="who", description="Show online users in TeamTalk"),
    BotCommand(command="help", description="Show this help message"),
    BotCommand(command="settings", description="Access interactive settings menu"),
]

ADMIN_COMMANDS: List[BotCommand] = USER_COMMANDS + [
    BotCommand(command="kick", description="Kick TT user (admin, via buttons)"),
    BotCommand(command="ban", description="Ban TT user (admin, via buttons)"),
    BotCommand(command="subscribers", description="View and manage subscribed users"),
]


async def set_telegram_commands(bot: Bot, admin_ids: List[int] = None):
    """
    Sets the bot commands for admins and default users.
    - Admin commands are set for each chat_id in admin_ids.
    - User commands are set for all private chats.
    """
    if admin_ids:
        for admin_id in admin_ids:
            try:
                scope = BotCommandScopeChat(chat_id=admin_id)
                await bot.set_my_commands(commands=ADMIN_COMMANDS, scope=scope)
                logger.info(f"Successfully set admin commands for admin_id {admin_id} in scope {scope!r}.")
            except TelegramAPIError as e:
                logger.error(f"Failed to set Telegram admin commands for admin_id {admin_id}, scope {scope!r}: {e}")
            except Exception as e:
                logger.error(f"An unexpected error occurred while setting admin commands for admin_id {admin_id}: {e}")

    try:
        default_scope = BotCommandScopeAllPrivateChats()
        await bot.set_my_commands(commands=USER_COMMANDS, scope=default_scope)
        logger.info(f"Successfully set user commands for scope {default_scope!r}.")
    except TelegramAPIError as e:
        logger.error(f"Failed to set Telegram user commands for scope {default_scope!r}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while setting user commands: {e}")
