import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)

async def set_telegram_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Start bot / Process deeplink"),
        BotCommand(command="who", description="Show online users in TeamTalk"),
        BotCommand(command="id", description="Get TeamTalk User ID (via buttons)"),
        BotCommand(command="help", description="Show this help message"),
        BotCommand(command="cl", description="Change language (e.g., /cl en)"),
        # Notification settings
        BotCommand(command="notify_all", description="Enable all join/leave notifications"),
        BotCommand(command="notify_join_off", description="Disable join notifications only"),
        BotCommand(command="notify_leave_off", description="Disable leave notifications only"),
        BotCommand(command="notify_none", description="Disable all join/leave notifications"),
        # Mute settings
        BotCommand(command="mute", description="Mute user (e.g., /mute user <tt_username>)"),
        BotCommand(command="unmute", description="Unmute user (e.g., /unmute user <tt_username>)"),
        BotCommand(command="mute_all", description="Mute all by default (except allow-list)"),
        BotCommand(command="unmute_all", description="Unmute all by default (except block-list)"),
        # Not on Online (NOON) feature
        BotCommand(command="toggle_noon", description="Toggle 'Not on Online' silent notifications"),
        BotCommand(command="my_noon_status", description="Check your 'Not on Online' status"),
        # Admin commands (will only work if user is admin)
        BotCommand(command="kick", description="Kick TT user (admin, via buttons)"),
        BotCommand(command="ban", description="Ban TT user (admin, via buttons)"),
    ]
    try:
        await bot.set_my_commands(commands=commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("Telegram bot commands updated successfully.")
    except TelegramAPIError as e:
        logger.error(f"Failed to set Telegram bot commands: {e}")
