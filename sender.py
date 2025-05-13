import asyncio
import enum
import logging
import os
import sys
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

import pytalk
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import UserStatusMode
from pytalk.instance import TeamTalkInstance
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as TeamTalkUser
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, delete, select
from sqlalchemy import Enum as SQLAEnum
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ttstr = pytalk.instance.sdk.ttstr

LOCALIZED_STRINGS = {
    "start_hello": {"en": "Hello! Use /help to see available commands.", "ru": "Привет! Используйте /help для просмотра доступных команд."},
    "deeplink_invalid_or_expired": {"en": "Invalid or expired deeplink.", "ru": "Недействительная или истекшая ссылка."},
    "deeplink_wrong_account": {"en": "This confirmation link was intended for a different Telegram account.", "ru": "Эта ссылка для подтверждения предназначена для другого Telegram аккаунта."},
    "deeplink_subscribed": {"en": "You have successfully subscribed to notifications.", "ru": "Вы успешно подписались на уведомления."},
    "deeplink_already_subscribed": {"en": "You are already subscribed to notifications.", "ru": "Вы уже подписаны на уведомления."},
    "deeplink_unsubscribed": {"en": "You have successfully unsubscribed from notifications.", "ru": "Вы успешно отписались от уведомления."},
    "deeplink_not_subscribed": {"en": "You were not subscribed to notifications.", "ru": "Вы не были подписаны на уведомления."},
    "deeplink_noon_confirm_missing_payload": {"en": "Error: Missing TeamTalk username in confirmation link.", "ru": "Ошибка: В ссылке подтверждения отсутствует имя пользователя TeamTalk."},
    "deeplink_noon_confirmed": {"en": "'Not on online' notifications enabled for TeamTalk user '{tt_username}'. You will receive silent notifications when this user is online on TeamTalk.", "ru": "Уведомления 'не в сети' включены для пользователя TeamTalk '{tt_username}'. Вы будете получать тихие уведомления, когда этот пользователь в сети TeamTalk."},
    "deeplink_invalid_action": {"en": "Invalid deeplink action.", "ru": "Неверное действие deeplink."},
    "error_occurred": {"en": "An error occurred.", "ru": "Произошла ошибка."},
    "tt_bot_not_connected": {"en": "TeamTalk bot is not connected.", "ru": "Бот TeamTalk не подключен."},
    "tt_error_getting_users": {"en": "Error getting users from TeamTalk.", "ru": "Ошибка получения пользователей из TeamTalk."},
    "who_channel_in": {"en": "in {channel_name}", "ru": "в {channel_name}"},
    "who_channel_under_server": {"en": "under server", "ru": "под сервером"},
    "who_channel_root": {"en": "in root channel", "ru": "в корневом канале"},
    "who_channel_unknown_location": {"en": "in unknown location", "ru": "в неизвестном месте"},
    "who_user_unknown": {"en": "unknown user", "ru": "неизвестный пользователь"},
    "who_and_separator": {"en": " and ", "ru": " и "},
    "who_users_count_singular": {"en": "user", "ru": "пользователь"},
    "who_users_count_plural_2_4": {"en": "users", "ru": "пользователя"},
    "who_users_count_plural_5_more": {"en": "users", "ru": "пользователей"},
    "who_header": {"en": "There are {user_count} {users_word} on the server:\n", "ru": "На сервере сейчас {user_count} {users_word}:\n"},
    "who_no_users_online": {"en": "No users found online.", "ru": "Пользователей онлайн не найдено."},
    "cl_prompt": {"en": "Please specify the language. Example: /cl en or /cl ru.", "ru": "Укажите язык. Пример: /cl en или /cl ru."},
    "cl_changed": {"en": "Language changed to {new_lang}.", "ru": "Язык изменен на {new_lang}."},
    "notify_all_set": {"en": "Join and leave notifications are enabled.", "ru": "Уведомления о входах и выходах включены."},
    "notify_join_off_set": {"en": "Only leave notifications are enabled.", "ru": "Включены только уведомления о выходах."},
    "notify_leave_off_set": {"en": "Only join notifications are enabled.", "ru": "Включены только уведомления о входах."},
    "notify_none_set": {"en": "Join and leave notifications are disabled.", "ru": "Уведомления о входах и выходах отключены."},
    "mute_prompt_user": {"en": "Please specify username to mute in format: /mute user <username>.", "ru": "Пожалуйста, укажите имя пользователя для мьюта в формате: /mute user <username>."},
    "mute_username_empty": {"en": "Username cannot be empty.", "ru": "Имя пользователя не может быть пустым."},
    "mute_already_muted": {"en": "User {username} was already muted.", "ru": "Пользователь {username} уже был замьючен."},
    "mute_now_muted": {"en": "User {username} is now muted.", "ru": "Пользователь {username} теперь замьючен."},
    "unmute_prompt_user": {"en": "Please specify username to unmute in format: /unmute user <username>.", "ru": "Пожалуйста, укажите имя пользователя для размьюта в формате: /unmute user <username>."},
    "unmute_now_unmuted": {"en": "User {username} is now unmuted.", "ru": "Пользователь {username} теперь размьючен."},
    "unmute_not_in_list": {"en": "User {username} was not in the mute list.", "ru": "Пользователь {username} не был в списке мьюта."},
    "mute_all_enabled": {"en": "Mute all for join/leave notifications enabled (only exceptions will be notified).", "ru": "Мьют всех для уведомлений о входе/выходе включен (уведомления будут приходить только для исключений)."},
    "unmute_all_disabled": {"en": "Mute all for join/leave notifications disabled (muted users won't be notified).", "ru": "Мьют всех для уведомлений о входе/выходе выключен (замьюченные пользователи не будут получать уведомления)."},
    "noon_not_configured": {"en": "The 'not on online' feature is not configured for your account. Please set it up via TeamTalk using `/not on online`.", "ru": "Функция 'не в сети' не настроена для вашего аккаунта. Пожалуйста, настройте ее через TeamTalk командой `/not on online`."},
    "noon_toggled_enabled": {"en": "'Not on online' notifications are now ENABLED for TeamTalk user '{tt_username}'. You will receive silent notifications when this user is online.", "ru": "Уведомления 'не в сети' теперь ВКЛЮЧЕНЫ для пользователя TeamTalk '{tt_username}'. Вы будете получать тихие уведомления, когда этот пользователь в сети."},
    "noon_toggled_disabled": {"en": "'Not on online' notifications are now DISABLED for TeamTalk user '{tt_username}'. Notifications will be sent normally.", "ru": "Уведомления 'не в сети' теперь ВЫКЛЮЧЕНЫ для пользователя TeamTalk '{tt_username}'. Уведомления будут приходить как обычно."},
    "noon_error_updating": {"en": "Error updating settings. Please try again.", "ru": "Ошибка обновления настроек. Пожалуйста, попробуйте снова."},
    "noon_status_not_configured": {"en": "'Not on online' feature is not configured for your account. Use `/not on online` in TeamTalk to set it up.", "ru": "Функция 'не в сети' не настроена для вашего аккаунта. Используйте `/not on online` в TeamTalk для настройки."},
    "noon_status_report": {"en": "'Not on online' notifications are {status} for TeamTalk user '{tt_username}'.", "ru": "Уведомления 'не в сети' {status_ru} для пользователя TeamTalk '{tt_username}'."},
    "noon_status_enabled_en": "ENABLED", "noon_status_disabled_en": "DISABLED",
    "noon_status_enabled_ru": "ВКЛЮЧЕНА", "noon_status_disabled_ru": "ВЫКЛЮЧЕНА",
    "callback_invalid_data": {"en": "Invalid data received.", "ru": "Получены неверные данные."},
    "callback_no_permission": {"en": "You do not have permission to execute this action.", "ru": "У вас нет прав на выполнение этого действия."},
    "callback_error_find_user_tt": {"en": "Error finding user on TeamTalk.", "ru": "Ошибка поиска пользователя в TeamTalk."},
    "callback_user_id_info": {"en": "User {user_nickname} has ID: {user_id}", "ru": "Пользователь {user_nickname} имеет ID: {user_id}"},
    "callback_user_kicked": {"en": "User {user_nickname} kicked from server.", "ru": "Пользователь {user_nickname} был исключен с сервера."},
    "callback_user_banned_kicked": {"en": "User {user_nickname} banned and kicked from server.", "ru": "Пользователь {user_nickname} был забанен и выкинут с сервера."},
    "callback_error_action_user": {"en": "Error {action}ing user {user_nickname}: {error}", "ru": "Ошибка {action_ru} пользователя {user_nickname}: {error}"},
    "callback_action_kick_gerund_ru": "исключения", "callback_action_ban_gerund_ru": "бана",
    "callback_user_not_found_anymore": {"en": "User not found on server anymore.", "ru": "Пользователь больше не найден на сервере."},
    "callback_unknown_action": {"en": "Unknown action.", "ru": "Неизвестное действие."},
    "toggle_ignore_error_processing": {"en": "Error processing request.", "ru": "Ошибка обработки запроса."},
    "toggle_ignore_error_empty_username": {"en": "Error: Empty username.", "ru": "Ошибка: Пустое имя пользователя."},
    "toggle_ignore_now_ignored": {"en": "User {nickname} is now ignored.", "ru": "Пользователь {nickname} теперь игнорируется."},
    "toggle_ignore_no_longer_ignored": {"en": "User {nickname} is no longer ignored.", "ru": "Пользователь {nickname} больше не игнорируется."},
    "toggle_ignore_button_text": {"en": "Toggle ignore status: {nickname}", "ru": "Переключить статус игнорирования: {nickname}"},
    "show_users_no_users_online": {"en": "No users online to select.", "ru": "Нет пользователей онлайн для выбора."},
    "show_users_no_other_users_online": {"en": "No other users online to select.", "ru": "Нет других пользователей онлайн для выбора."},
    "show_users_select_id": {"en": "Select a user to get ID:", "ru": "Выберите пользователя для получения ID:"},
    "show_users_select_kick": {"en": "Select a user to kick:", "ru": "Выберите пользователя для кика:"},
    "show_users_select_ban": {"en": "Select a user to ban:", "ru": "Выберите пользователя для бана:"},
    "show_users_select_default": {"en": "Select a user:", "ru": "Выберите пользователя:"},
    "unknown_command": {"en": "Unknown command. Use /help to see available commands.", "ru": "Неизвестная команда. Используйте /help для просмотра доступных команд."},
    "tt_reply_success": {"en": "Message sent to Telegram successfully.", "ru": "Сообщение успешно отправлено в Telegram."},
    "tt_reply_fail_invalid_token": {"en": "Failed to send message: Invalid token.", "ru": "Не удалось отправить сообщение: неверный токен."},
    "tt_reply_fail_api_error": {"en": "Failed to send message: Telegram API Error: {error}", "ru": "Не удалось отправить сообщение: Ошибка Telegram API: {error}"},
    "tt_reply_fail_generic_error": {"en": "Failed to send message: {error}", "ru": "Не удалось отправить сообщение: {error}"},
    "tt_subscribe_deeplink_text": {"en": "Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}", "ru": "Нажмите на эту ссылку, чтобы подписаться на уведомления (ссылка действительна 5 минут):\n{deeplink_url}"},
    "tt_subscribe_error": {"en": "An error occurred while processing the subscription request.", "ru": "Произошла ошибка при обработке запроса на подписку."},
    "tt_unsubscribe_deeplink_text": {"en": "Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}", "ru": "Нажмите на эту ссылку, чтобы отписаться от уведомлений (ссылка действительна 5 минут):\n{deeplink_url}"},
    "tt_unsubscribe_error": {"en": "An error occurred while processing the unsubscription request.", "ru": "Произошла ошибка при обработке запроса на отписку."},
    "tt_admin_cmd_no_permission": {"en": "You do not have permission to use this command.", "ru": "У вас нет прав на использование этой команды."},
    "tt_add_admin_prompt_ids": {"en": "Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432", "ru": "Пожалуйста, укажите Telegram ID после команды. Пример: /add_admin 12345678 98765432"},
    "tt_add_admin_success": {"en": "Successfully added {count} admin(s).", "ru": "Успешно добавлено администраторов: {count}."},
    "tt_add_admin_error_already_admin": {"en": "ID {telegram_id} is already an admin or failed to add.", "ru": "ID {telegram_id} уже является администратором или не удалось добавить."},
    "tt_add_admin_error_invalid_id": {"en": "'{telegram_id_str}' is not a valid numeric Telegram ID.", "ru": "'{telegram_id_str}' не является действительным числовым Telegram ID."},
    "tt_admin_errors_header": {"en": "Errors:\n- ", "ru": "Ошибки:\n- "},
    "tt_admin_info_errors_header": {"en": "Info/Errors:\n- ", "ru": "Информация/Ошибки:\n- "},
    "tt_admin_no_valid_ids": {"en": "No valid IDs provided.", "ru": "Не предоставлено действительных ID."},
    "tt_admin_error_processing": {"en": "An error occurred while processing the command.", "ru": "Произошла ошибка при обработке команды."},
    "tt_remove_admin_prompt_ids": {"en": "Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432", "ru": "Пожалуйста, укажите Telegram ID после команды. Пример: /remove_admin 12345678 98765432"},
    "tt_remove_admin_success": {"en": "Successfully removed {count} admin(s).", "ru": "Успешно удалено администраторов: {count}."},
    "tt_remove_admin_error_not_found": {"en": "Admin with ID {telegram_id} not found.", "ru": "Администратор с ID {telegram_id} не найден."},
    "tt_noon_usage": {"en": "Usage: /not on online", "ru": "Использование: /not on online"},
    "tt_noon_confirm_deeplink_text": {"en": "To enable 'not on online' notifications for your TeamTalk user '{tt_username}', please open this link in Telegram and confirm (link valid for 5 minutes):\n{deeplink_url}", "ru": "Чтобы включить уведомления 'не в сети' для вашего пользователя TeamTalk '{tt_username}', пожалуйста, откройте эту ссылку в Telegram и подтвердите (ссылка действительна 5 минут):\n{deeplink_url}"},
    "tt_noon_error_processing": {"en": "An error occurred while processing the request.", "ru": "Произошла ошибка при обработке запроса."},
    "tt_unknown_command": {"en": "Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help.", "ru": "Неизвестная команда. Доступные команды: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help."},
    "tt_forward_message_text": {"en": "Message from server {server_name}\nFrom {sender_display}:\n\n{message_text}", "ru": "Сообщение с сервера {server_name}\nОт {sender_display}:\n\n{message_text}"},
    "join_notification": {"en": "User {user_nickname} joined server {server_name}", "ru": "{user_nickname} присоединился к серверу {server_name}"},
    "leave_notification": {"en": "User {user_nickname} left server {server_name}", "ru": "{user_nickname} покинул сервер {server_name}"},
    "help_text_en": (
            "This bot forwards messages from a TeamTalk server to Telegram and sends join/leave notifications.\n\n"
            "**Telegram Commands:**\n"
            "/who - Show online users.\n"
            "/id - Get ID of a user (via buttons).\n"
            "/kick - Kick a user from the server (admin, via buttons).\n"
            "/ban - Ban a user from the server (admin, via buttons).\n"
            "/cl `en|ru` - Change bot language.\n"
            "/notify_all - Enable all join/leave notifications.\n"
            "/notify_join_off - Disable join notifications.\n"
            "/notify_leave_off - Disable leave notifications.\n"
            "/notify_none - Disable all join/leave notifications.\n"
            "/start - Start bot or process deeplink.\n"
            "/mute user `<username>` - Add user to mute list (don't receive notifications).\n"
            "/unmute user `<username>` - Remove user from mute list.\n"
            "/mute_all - Enable 'mute all' mode (only get notifications for exceptions in the mute list).\n"
            "/unmute_all - Disable 'mute all' mode (get notifications for everyone except the mute list).\n"
            "/toggle_noon - Toggle silent notifications if your linked TeamTalk user is online.\n"
            "/my_noon_status - Check your 'not on online' feature status.\n"
            "/help - Show this help message.\n\n"
            "**Note on Mutes and 'Toggle ignore status' Buttons:**\n"
            "- The 'Toggle ignore status' button under join/leave messages manages your personal mute list for that TeamTalk user.\n"
            "- When `/mute_all` is **disabled** (default): the mute list contains users you **don't** get notifications from. Pressing the button toggles if the user is in this list.\n"
            "- When `/mute_all` is **enabled**: the mute list contains users you **do** get notifications from (exceptions). Pressing the button toggles if the user is in this exception list.\n"
            "- `/unmute_all` always disables `/mute_all` and clears the list.\n\n"
            "**Note on 'Not on Online' feature (/toggle_noon):**\n"
            "- First, set it up via TeamTalk: `/not on online` in a private message to the TeamTalk bot.\n"
            "- After confirming via the link in Telegram, this feature will be active.\n"
            "- If your linked TeamTalk user is online, Telegram notifications will be silent.\n\n"
            "**TeamTalk Commands (in private message to the bot):**\n"
            "/sub - Get a link to subscribe to notifications.\n"
            "/unsub - Get a link to unsubscribe from notifications.\n"
            "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Add bot admin (ADMIN_USERNAME from .env only).\n"
            "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Remove bot admin (ADMIN_USERNAME from .env only).\n"
            "/not on online - Set up silent notifications for when you are online in TeamTalk.\n"
            "/help - Show help."
    ),
    "help_text_ru": (
            "Этот бот пересылает сообщения с TeamTalk сервера в Telegram и уведомляет о входе/выходе пользователей.\n\n"
            "**Команды Telegram:**\n"
            "/who - Показать онлайн пользователей.\n"
            "/id - Получить ID пользователя (через кнопки).\n"
            "/kick - Кикнуть пользователя с сервера (админ, через кнопки).\n"
            "/ban - Забанить пользователя на сервере (админ, через кнопки).\n"
            "/cl `en|ru` - Изменить язык бота.\n"
            "/notify_all - Включить все уведомления.\n"
            "/notify_join_off - Выключить уведомления о входах.\n"
            "/notify_leave_off - Выключить уведомления о выходах.\n"
            "/notify_none - Выключить все уведомления.\n"
            "/start - Запустить бота или обработать deeplink.\n"
            "/mute user `<username>` - Добавить пользователя в список мьюта (не получать уведомления).\n"
            "/unmute user `<username>` - Удалить пользователя из списка мьюта.\n"
            '/mute_all - Включить режим "мьют всех" (уведомления только для исключений из списка мьюта).\n'
            '/unmute_all - Выключить режим "мьют всех" (уведомления для всех, кроме списка мьюта).\n'
            "/toggle_noon - Включить/выключить тихие уведомления, если связанный пользователь TeamTalk онлайн.\n"
            "/my_noon_status - Проверить статус функции 'не в сети'.\n"
            "/help - Показать это сообщение.\n\n"
            "**Примечание по мьютам и кнопкам 'Переключить статус игнорирования':**\n"
            "- Кнопка 'Переключить статус игнорирования' под сообщениями о входе/выходе управляет вашим персональным списком мьюта для этого пользователя TeamTalk.\n"
            "- Когда `/mute_all` **выключен** (по умолчанию): список мьюта содержит тех, от кого **не** приходят уведомления. Нажатие кнопки переключает, будет ли пользователь в этом списке.\n"
            "- Когда `/mute_all` **включен**: список мьюта содержит тех, от кого **приходят** уведомления (исключения). Нажатие кнопки переключает, будет ли пользователь в этом списке исключений.\n"
            "- `/unmute_all` всегда выключает `/mute_all` и очищает список.\n\n"
            "**Примечание по функции 'не в сети' (/toggle_noon):**\n"
            "- Сначала настройте через TeamTalk: `/not on online` в личные сообщения боту TeamTalk.\n"
            "- После подтверждения по ссылке в Telegram, эта функция будет активна.\n"
            "- Если связанный пользователь TeamTalk онлайн, уведомления в Telegram будут приходить без звука.\n\n"
            "**Команды TeamTalk (в личные сообщения боту):**\n"
            "/sub - Получить ссылку для подписки на уведомления.\n"
            "/unsub - Получить ссылку для отписки от уведомлений.\n"
            "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Добавить админа бота (только для ADMIN_USERNAME из .env).\n"
            "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Удалить админа бота (только для ADMIN_USERNAME из .env).\n"
            "/not on online - Настроить тихие уведомления, когда вы онлайн в TeamTalk.\n"
            "/help - Показать справку."
    )
}

def get_text(key: str, lang: str, **kwargs) -> str:
    default_lang = "en"
    message_template = LOCALIZED_STRINGS.get(key, {}).get(lang)
    if message_template is None:
        message_template = LOCALIZED_STRINGS.get(key, {}).get(default_lang, f"[{key}_{lang}]")
    
    try:
        return message_template.format(**kwargs)
    except KeyError as e:
        logging.warning(f"Missing placeholder {e} for key '{key}' in lang '{lang}' with kwargs {kwargs}")
        return message_template


class InfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.INFO

log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.addFilter(InfoFilter())

root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def load_config(env_path: str | None = None) -> dict[str, Any]:
    load_dotenv(dotenv_path=env_path)
    config_data = {
        "TG_BOT_TOKEN": os.getenv("TG_BOT_TOKEN"),
        "TG_EVENT_TOKEN": os.getenv("TELEGRAM_BOT_EVENT_TOKEN") or os.getenv("TG_BOT_TOKEN"),
        "TG_BOT_MESSAGE_TOKEN": os.getenv("TG_BOT_MESSAGE_TOKEN"),
        "TG_ADMIN_CHAT_ID": os.getenv("TG_ADMIN_CHAT_ID"),
        "HOSTNAME": os.getenv("HOST_NAME"),
        "PORT": int(os.getenv("PORT", "9987")),
        "ENCRYPTED": os.getenv("ENCRYPTED") == "1",
        "USERNAME": os.getenv("USER_NAME"),
        "PASSWORD": os.getenv("PASSWORD"),
        "CHANNEL": os.getenv("CHANNEL"),
        "CHANNEL_PASSWORD": os.getenv("CHANNEL_PASSWORD"),
        "NICKNAME": os.getenv("NICK_NAME"),
        "STATUS_TEXT": os.getenv("STATUS_TEXT", ""),
        "CLIENT_NAME": os.getenv("CLIENT_NAME") or "TTTM",
        "SERVER_NAME": os.getenv("SERVER_NAME"),
        "ADMIN_USERNAME": os.getenv("ADMIN"),
        "GLOBAL_IGNORE_USERNAME": os.getenv("GLOBAL_IGNORE_USERNAME"),
        "DATABASE_FILE": os.getenv("DATABASE_FILE", "bot_data.db"),
    }
    if not config_data["TG_EVENT_TOKEN"] and not config_data["TG_BOT_TOKEN"]:
        raise ValueError("Missing required environment variable: TG_BOT_TOKEN or TELEGRAM_BOT_EVENT_TOKEN. Check .env file.")
    if not config_data["HOSTNAME"] or not config_data["USERNAME"] or not config_data["PASSWORD"] or not config_data["CHANNEL"] or not config_data["NICKNAME"]:
        raise ValueError("Missing other required environment variables. Check .env file.")
    if config_data["TG_ADMIN_CHAT_ID"]:
        try:
            config_data["TG_ADMIN_CHAT_ID"] = int(config_data["TG_ADMIN_CHAT_ID"])
        except ValueError:
            raise ValueError("TG_ADMIN_CHAT_ID must be a valid integer.")
    return config_data

MIN_ARGS_FOR_ENV_PATH = 2
config = load_config(sys.argv[1] if len(sys.argv) >= MIN_ARGS_FOR_ENV_PATH else None)

tg_bot_event = Bot(token=config["TG_EVENT_TOKEN"])
tg_bot_message = Bot(token=config["TG_BOT_MESSAGE_TOKEN"]) if config["TG_BOT_MESSAGE_TOKEN"] else None

DATABASE_FILES = {"main": config["DATABASE_FILE"]}
async_engines = {db_name: create_async_engine(f"sqlite+aiosqlite:///{db_file}") for db_name, db_file in DATABASE_FILES.items()}
SessionFactory = sessionmaker(async_engines["main"], expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

async def init_db() -> None:
    async with async_engines["main"].begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")

class SubscribedUser(Base):
    __tablename__ = "subscribed_users"
    telegram_id = Column(Integer, primary_key=True, autoincrement=True)

class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(Integer, primary_key=True, autoincrement=True)

class Deeplink(Base):
    __tablename__ = "deeplinks"
    token = Column(String, primary_key=True)
    action = Column(String)
    payload = Column(String, nullable=True)
    expected_telegram_id = Column(Integer, nullable=True)
    expiry_time = Column(DateTime)

class NotificationSetting(enum.Enum):
    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"

class UserSettings(Base):
    __tablename__ = "user_settings"
    telegram_id = Column(Integer, primary_key=True)
    language = Column(String, default="en")
    notification_settings = Column(SQLAEnum(NotificationSetting), default=NotificationSetting.ALL)
    muted_users = Column(String, default="")
    mute_all = Column(Boolean, default=False)
    teamtalk_username = Column(String, nullable=True, index=True)
    not_on_online_enabled = Column(Boolean, default=False)
    not_on_online_confirmed = Column(Boolean, default=False)
    __table_args__ = (Index("ix_user_settings_telegram_id", "telegram_id"),)

@dataclass
class UserSpecificSettings:
    language: str = "en"
    notification_settings: NotificationSetting = NotificationSetting.ALL
    muted_users_set: set[str] = field(default_factory=set)
    mute_all_flag: bool = False
    teamtalk_username: str | None = None
    not_on_online_enabled: bool = False
    not_on_online_confirmed: bool = False

    @classmethod
    def from_db_row(cls, settings_row: UserSettings | None):
        if not settings_row:
            return cls()
        return cls(
            language=settings_row.language,
            notification_settings=settings_row.notification_settings,
            muted_users_set=set(settings_row.muted_users.split(",")) if settings_row.muted_users else set(),
            mute_all_flag=settings_row.mute_all,
            teamtalk_username=settings_row.teamtalk_username,
            not_on_online_enabled=settings_row.not_on_online_enabled,
            not_on_online_confirmed=settings_row.not_on_online_confirmed,
        )

    def to_cache_dict(self) -> dict[str, Any]:
         return {
            "language": self.language,
            "notification_settings": self.notification_settings,
            "mute_settings": {"muted_users": self.muted_users_set, "mute_all": self.mute_all_flag},
            "teamtalk_username": self.teamtalk_username,
            "not_on_online_enabled": self.not_on_online_enabled,
            "not_on_online_confirmed": self.not_on_online_confirmed,
        }

USER_SETTINGS_CACHE: dict[int, UserSpecificSettings] = {}
login_complete_time: datetime | None = None

async def load_user_settings_to_cache(session_factory: sessionmaker) -> None:
    logger.info("Loading user settings into cache...")
    async with session_factory() as session:
        result = await session.execute(select(UserSettings))
        user_settings_list = result.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = UserSpecificSettings.from_db_row(settings_row)
    logger.info(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")

async def _async_load_user_settings(telegram_id: int, session: AsyncSession) -> UserSpecificSettings:
    user_settings_row = await session.get(UserSettings, telegram_id)
    if user_settings_row:
        specific_settings = UserSpecificSettings.from_db_row(user_settings_row)
        USER_SETTINGS_CACHE[telegram_id] = specific_settings
        return specific_settings
    else:
        default_settings = UserSpecificSettings()
        USER_SETTINGS_CACHE[telegram_id] = default_settings
        new_settings_row = UserSettings(
            telegram_id=telegram_id,
            language=default_settings.language,
            notification_settings=default_settings.notification_settings,
            muted_users=",".join(sorted(list(default_settings.muted_users_set))),
            mute_all=default_settings.mute_all_flag,
            teamtalk_username=default_settings.teamtalk_username,
            not_on_online_enabled=default_settings.not_on_online_enabled,
            not_on_online_confirmed=default_settings.not_on_online_confirmed,
        )
        session.add(new_settings_row)
        await session.commit()
        logger.info(f"Created default settings for user {telegram_id}")
        return default_settings

async def db_add(session: AsyncSession, model: Base, **kwargs):
    try:
        if model in [SubscribedUser, Admin] and "telegram_id" in kwargs:
             existing_record = await session.get(model, kwargs["telegram_id"])
             if existing_record:
                 logger.warning(f"Record already exists in {model.__tablename__} for id {kwargs['telegram_id']}")
                 return False

        new_db_record = model(**kwargs)
        session.add(new_db_record)
        await session.commit()
        logger.info(f"Added record to {model.__tablename__}: {kwargs}")
        return True
    except Exception as e:
        logger.error(f"Error adding to DB ({model.__tablename__}): {e}")
        await session.rollback()
        return False

async def db_remove(session: AsyncSession, model: Base, telegram_id: int):
    try:
        record_to_remove = await session.get(model, telegram_id)
        if record_to_remove:
            await session.delete(record_to_remove)
            await session.commit()
            logger.info(f"Removed record from {model.__tablename__} for id {telegram_id}")
            return True
        logger.warning(f"Record not found in {model.__tablename__} for id {telegram_id}")
        return False
    except Exception as e:
        logger.error(f"Error removing from DB ({model.__tablename__}): {e}")
        await session.rollback()
        return False

async def db_get_all_telegram_ids(session: AsyncSession, model: Base) -> list[int]:
    try:
        result = await session.execute(select(model.telegram_id))
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Error getting telegram_ids from DB ({model.__tablename__}): {e}")
        return []

async def add_subscriber(session: AsyncSession, telegram_id: int):
    return await db_add(session, SubscribedUser, telegram_id=telegram_id)

async def remove_subscriber(session: AsyncSession, telegram_id: int):
    return await db_remove(session, SubscribedUser, telegram_id)

async def get_all_subscribers(session: AsyncSession):
    return await db_get_all_telegram_ids(session, SubscribedUser)

async def add_admin(session: AsyncSession, telegram_id: int):
    return await db_add(session, Admin, telegram_id=telegram_id)

async def remove_admin_db(session: AsyncSession, telegram_id: int):
    return await db_remove(session, Admin, telegram_id)

async def get_all_admins(session: AsyncSession) -> list[int]:
    return await db_get_all_telegram_ids(session, Admin)

async def is_admin(session: AsyncSession, telegram_id: int) -> bool:
    admin_db_record = await session.get(Admin, telegram_id)
    return admin_db_record is not None

async def create_deeplink(session: AsyncSession, action: str, payload: str | None = None, expected_telegram_id: int | None = None) -> str:
    token_str = str(uuid.uuid4())
    expiry_time_val = datetime.utcnow() + timedelta(minutes=5)
    deeplink_obj = Deeplink(
        token=token_str,
        action=action,
        payload=payload,
        expected_telegram_id=expected_telegram_id,
        expiry_time=expiry_time_val
    )
    session.add(deeplink_obj)
    await session.commit()
    logger.info(f"Created deeplink: token={token_str}, action={action}, payload={payload}, expected_id={expected_telegram_id}")
    return token_str

async def get_deeplink(session: AsyncSession, token: str) -> Deeplink | None:
    result = await session.execute(select(Deeplink).where(Deeplink.token == token))
    deeplink_obj = result.scalar_one_or_none()
    if deeplink_obj and deeplink_obj.expiry_time and deeplink_obj.expiry_time < datetime.utcnow():
        logger.warning(f"Deeplink {token} expired.")
        await session.delete(deeplink_obj)
        await session.commit()
        return None
    return deeplink_obj

async def delete_deeplink(session: AsyncSession, token: str):
    stmt = delete(Deeplink).where(Deeplink.token == token)
    result = await session.execute(stmt)
    await session.commit()
    if result.rowcount > 0:
        logger.info(f"Deleted deeplink {token}")
    else:
        logger.warning(f"Deeplink {token} not found for deletion.")

tt_bot = pytalk.TeamTalkBot(client_name=config["CLIENT_NAME"])
current_tt_instance: TeamTalkInstance | None = None

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: sessionmaker):
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)

class UserSettingsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_obj = data.get("event_from_user")
        session_obj: AsyncSession | None = data.get("session")
        user_specific_settings: UserSpecificSettings

        if user_obj and session_obj:
            telegram_id_val = user_obj.id
            if telegram_id_val not in USER_SETTINGS_CACHE:
                user_specific_settings = await _async_load_user_settings(telegram_id_val, session_obj)
            else:
                user_specific_settings = USER_SETTINGS_CACHE[telegram_id_val]
        else:
            user_specific_settings = UserSpecificSettings()

        data["user_specific_settings"] = user_specific_settings
        data["language"] = user_specific_settings.language
        data["notification_settings"] = user_specific_settings.notification_settings
        data["mute_settings"] = {"muted_users": user_specific_settings.muted_users_set, "mute_all": user_specific_settings.mute_all_flag}
        return await handler(event, data)


class TeamTalkInstanceMiddleware(BaseMiddleware):
    def __init__(self, tt_bot_instance: pytalk.TeamTalkBot):
        super().__init__()
        self.tt_bot_instance = tt_bot_instance

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["tt_instance"] = current_tt_instance
        return await handler(event, data)

class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user_obj = event.from_user
        if not user_obj:
            return False
        return await is_admin(session, user_obj.id)

async def send_telegram_message(
    token: str,
    chat_id: int,
    text: str,
    language: str = "en",
    reply_tt: Callable | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    tt_instance_for_check: TeamTalkInstance | None = None
) -> bool:
    bot_to_use = tg_bot_event if token == config["TG_EVENT_TOKEN"] else tg_bot_message
    if not bot_to_use:
        logger.error(f"No Telegram bot instance available for token: {token}")
        if reply_tt:
            reply_tt(get_text("tt_reply_fail_invalid_token", language))
        return False

    send_silently = False
    recipient_settings = USER_SETTINGS_CACHE.get(chat_id)

    if recipient_settings and \
       recipient_settings.not_on_online_enabled and \
       recipient_settings.not_on_online_confirmed and \
       recipient_settings.teamtalk_username and \
       tt_instance_for_check:

        tt_username_to_check = recipient_settings.teamtalk_username
        try:
            is_tt_user_online = False
            if tt_instance_for_check.connected and tt_instance_for_check.logged_in:
                all_online_users = tt_instance_for_check.server.get_users()
                for online_user in all_online_users:
                    if ttstr(online_user.username) == tt_username_to_check:
                        is_tt_user_online = True
                        break
            else:
                logger.warning(f"Cannot check TT status for {tt_username_to_check}, TT instance not ready for chat_id {chat_id}.")

            if is_tt_user_online:
                send_silently = True
                logger.info(f"Sending message to {chat_id} silently as their linked TT user '{tt_username_to_check}' is online.")
        except Exception as e:
            logger.warning(f"Could not check TeamTalk status for user '{tt_username_to_check}' (TG ID: {chat_id}): {e}")

    message_sent = False
    try:
        await bot_to_use.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_notification=send_silently
            )
        message_sent = True

    except (TelegramForbiddenError, TelegramAPIError) as e:
        if "bot was blocked by the user" in str(e).lower():
            logger.warning(f"User {chat_id} blocked the bot. Unsubscribing...")
            try:
                async with SessionFactory() as unsubscribe_session:
                    removed = await remove_subscriber(unsubscribe_session, chat_id)
                if removed:
                    logger.info(f"Successfully unsubscribed blocked user {chat_id}.")
                else:
                    logger.info(f"User {chat_id} was likely already unsubscribed (remove_subscriber returned False).")

                USER_SETTINGS_CACHE.pop(chat_id, None)
                logger.info(f"Removed user {chat_id} from settings cache.")

            except Exception as db_err:
                logger.error(f"Failed to unsubscribe blocked user {chat_id} from DB: {db_err}")
            message_sent = False
        else:
            logger.error(f"Telegram API error sending to {chat_id}: {e}")
            if reply_tt:
                reply_tt(get_text("tt_reply_fail_api_error", language, error=str(e)))
            message_sent = False
    except Exception as e:
        logger.error(f"Error sending Telegram message to {chat_id}: {e}")
        if reply_tt:
            reply_tt(get_text("tt_reply_fail_generic_error", language, error=str(e)))
        message_sent = False

    if message_sent and reply_tt:
        reply_tt(get_text("tt_reply_success", language))
    return message_sent


async def send_telegram_messages(
    token: str,
    chat_ids: list[int],
    text_generator: Callable[[str], str],
    session: AsyncSession,
    reply_markup_generator: Callable[[str, str, str, int], InlineKeyboardMarkup | None] | None = None,
    tt_user_username_for_markup: str | None = None,
    tt_user_nickname_for_markup: str | None = None,
    tt_instance_for_check: TeamTalkInstance | None = None
):
    tasks_list = []
    for chat_id_val in chat_ids:
        user_settings_val = USER_SETTINGS_CACHE.get(chat_id_val)
        language_val = user_settings_val.language if user_settings_val else "en"
        text_val = text_generator(language_val)

        current_reply_markup_val = None
        if reply_markup_generator and tt_user_username_for_markup and tt_user_nickname_for_markup:
            current_reply_markup_val = reply_markup_generator(tt_user_username_for_markup, tt_user_nickname_for_markup, language_val, chat_id_val)

        tasks_list.append(send_telegram_message(
            token,
            chat_id_val,
            text_val,
            language_val,
            reply_markup=current_reply_markup_val,
            tt_instance_for_check=tt_instance_for_check
            ))
    await asyncio.gather(*tasks_list)

user_commands_router = Router(name="user_commands")
settings_router = Router(name="settings")
admin_router = Router(name="admin_commands")
callback_router = Router(name="callbacks")
catch_all_router = Router(name="catch_all")


async def _handle_subscribe_deeplink(session: AsyncSession, telegram_id: int, language: str) -> str:
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} subscribed via deeplink.")
        return get_text("deeplink_subscribed", language)
    return get_text("deeplink_already_subscribed", language)

async def _handle_unsubscribe_deeplink(session: AsyncSession, telegram_id: int, language: str) -> str:
    if await remove_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} unsubscribed via deeplink.")
        USER_SETTINGS_CACHE.pop(telegram_id, None)
        logger.info(f"Removed user {telegram_id} from settings cache after unsubscribe.")
        return get_text("deeplink_unsubscribed", language)
    return get_text("deeplink_not_subscribed", language)

async def _handle_confirm_noon_deeplink(session: AsyncSession, telegram_id: int, language: str, payload: str | None) -> str:
    tt_username_from_payload = payload
    if not tt_username_from_payload:
        logger.error("Deeplink for 'confirm_not_on_online' missing payload.")
        return get_text("deeplink_noon_confirm_missing_payload", language)

    db_user_settings = await session.get(UserSettings, telegram_id)
    if not db_user_settings:
        db_user_settings = UserSettings(telegram_id=telegram_id)
        session.add(db_user_settings)

    db_user_settings.teamtalk_username = tt_username_from_payload
    db_user_settings.not_on_online_enabled = True
    db_user_settings.not_on_online_confirmed = True
    await session.commit()

    if telegram_id in USER_SETTINGS_CACHE:
        USER_SETTINGS_CACHE[telegram_id].teamtalk_username = tt_username_from_payload
        USER_SETTINGS_CACHE[telegram_id].not_on_online_enabled = True
        USER_SETTINGS_CACHE[telegram_id].not_on_online_confirmed = True
    else:
        await _async_load_user_settings(telegram_id, session)

    logger.info(f"User {telegram_id} confirmed 'not on online' for TT user {tt_username_from_payload} via deeplink.")
    return get_text("deeplink_noon_confirmed", language, tt_username=html.quote(tt_username_from_payload))

DEEPLINK_ACTION_HANDLERS: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {
    "subscribe": _handle_subscribe_deeplink,
    "unsubscribe": _handle_unsubscribe_deeplink,
    "confirm_not_on_online": _handle_confirm_noon_deeplink,
}

@user_commands_router.message(Command("start"))
async def start_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    token_val = command.args
    if token_val:
        await handle_deeplink(message, token_val, session, language, user_specific_settings)
    else:
        await message.reply(get_text("start_hello", language))

async def handle_deeplink(message: Message, token: str, session: AsyncSession, language: str, user_specific_settings: UserSpecificSettings):
    deeplink_obj = await get_deeplink(session, token)
    if not deeplink_obj:
        await message.reply(get_text("deeplink_invalid_or_expired", language))
        return

    telegram_id_val = message.from_user.id
    reply_text_val = get_text("error_occurred", language)

    if deeplink_obj.expected_telegram_id and deeplink_obj.expected_telegram_id != telegram_id_val:
        await message.reply(get_text("deeplink_wrong_account", language))
        return

    handler = DEEPLINK_ACTION_HANDLERS.get(deeplink_obj.action)
    if handler:
        if deeplink_obj.action == "confirm_not_on_online":
            reply_text_val = await handler(session, telegram_id_val, language, deeplink_obj.payload)
        else:
            reply_text_val = await handler(session, telegram_id_val, language)
    else:
        reply_text_val = get_text("deeplink_invalid_action", language)
        logger.warning(f"Invalid deeplink action '{deeplink_obj.action}' for token {token}")

    await message.reply(reply_text_val)
    await delete_deeplink(session, token)


def _get_user_display_channel_name(user_obj: TeamTalkUser, is_caller_admin: bool, language: str) -> str:
    channel_obj = user_obj.channel
    user_display_channel_name_val = ""
    is_channel_hidden_val = False

    if channel_obj:
        try:
            if (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0:
                is_channel_hidden_val = True
        except AttributeError:
            logger.warning(f"Could not determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden.")
        except Exception as e_chan:
            logger.error(f"Error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}")

    if is_caller_admin:
        if channel_obj and channel_obj.id != 1 and channel_obj.id != 0 and channel_obj.id != -1:
            user_display_channel_name_val = get_text("who_channel_in", language, channel_name=ttstr(channel_obj.name))
        elif not channel_obj or channel_obj.id in [0, -1]:
            user_display_channel_name_val = get_text("who_channel_under_server", language)
        else:
            user_display_channel_name_val = get_text("who_channel_root", language)
    elif is_channel_hidden_val:
        user_display_channel_name_val = get_text("who_channel_under_server", language)
    elif channel_obj and channel_obj.id != 1 and channel_obj.id != 0 and channel_obj.id != -1:
        user_display_channel_name_val = get_text("who_channel_in", language, channel_name=ttstr(channel_obj.name))
    elif not channel_obj or channel_obj.id in [0, -1]:
        user_display_channel_name_val = get_text("who_channel_under_server", language)
    else:
        user_display_channel_name_val = get_text("who_channel_root", language)

    return user_display_channel_name_val or get_text("who_channel_unknown_location", language)


@user_commands_router.message(Command("who"))
async def who_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None,
    session: AsyncSession
):
    if not tt_instance:
        await message.reply(get_text("tt_bot_not_connected", language))
        return

    try:
        all_users_list = tt_instance.server.get_users()
    except Exception as e:
        logger.error(f"Failed to get users from TT: {e}")
        await message.reply(get_text("tt_error_getting_users", language))
        return

    is_caller_admin_val = await is_admin(session, message.from_user.id)
    users_to_display_count_val = 0
    channels_display_data_val: dict[str, list[str]] = {}

    for user_obj in all_users_list:
        user_display_channel_name_val = _get_user_display_channel_name(user_obj, is_caller_admin_val, language)

        if user_display_channel_name_val not in channels_display_data_val:
            channels_display_data_val[user_display_channel_name_val] = []

        user_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or get_text("who_user_unknown", language)
        channels_display_data_val[user_display_channel_name_val].append(user_nickname_val)
        users_to_display_count_val += 1

    user_count_val = users_to_display_count_val
    channel_info_parts_val = []

    for display_channel_name_val, users_in_channel_list_val in channels_display_data_val.items():
        user_text_segment_val = ""
        if users_in_channel_list_val:
            if len(users_in_channel_list_val) > 1:
                user_separator_val = get_text("who_and_separator", language)
                user_list_except_last_segment_val = ", ".join(users_in_channel_list_val[:-1])
                user_text_segment_val = f"{user_list_except_last_segment_val}{user_separator_val}{users_in_channel_list_val[-1]}"
            else:
                user_text_segment_val = users_in_channel_list_val[0]
            channel_info_parts_val.append(f"{user_text_segment_val} {display_channel_name_val}")

    users_word_total_val = ""
    if language == "ru":
        if user_count_val == 1: users_word_total_val = get_text("who_users_count_singular", "ru")
        elif 1 < user_count_val < 5: users_word_total_val = get_text("who_users_count_plural_2_4", "ru")
        else: users_word_total_val = get_text("who_users_count_plural_5_more", "ru")
    else: 
        users_word_total_val = get_text("who_users_count_singular", "en") if user_count_val == 1 else get_text("who_users_count_plural_5_more", "en")


    text_reply = get_text("who_header", language, user_count=user_count_val, users_word=users_word_total_val)

    if channel_info_parts_val:
        text_reply += "\n".join(channel_info_parts_val)
    else:
         text_reply += get_text("who_no_users_online", language)

    await message.reply(text_reply)

@user_commands_router.message(Command("id"))
async def id_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await show_user_buttons(message, "id", language, tt_instance)

@user_commands_router.message(Command("help"))
async def help_command_handler(message: Message, language: str):
    help_text_key = "help_text_ru" if language == "ru" else "help_text_en"
    await message.reply(get_text(help_text_key, language))

@settings_router.message(Command("cl"))
async def cl_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not command.args or command.args.lower() not in ["en", "ru"]:
        await message.reply(get_text("cl_prompt", language))
        return

    new_lang_val = command.args.lower()
    telegram_id_val = message.from_user.id

    user_settings_obj = await session.get(UserSettings, telegram_id_val)
    if not user_settings_obj:
        user_settings_obj = UserSettings(telegram_id=telegram_id_val, language=new_lang_val)
        session.add(user_settings_obj)
    else:
        user_settings_obj.language = new_lang_val
    await session.commit()

    user_specific_settings.language = new_lang_val
    USER_SETTINGS_CACHE[telegram_id_val] = user_specific_settings

    await message.reply(get_text("cl_changed", new_lang_val, new_lang=new_lang_val))

async def set_notification_settings_command(message: Message, settings_val: NotificationSetting, session: AsyncSession, language: str, user_specific_settings: UserSpecificSettings):
    telegram_id_val = message.from_user.id
    user_settings_obj = await session.get(UserSettings, telegram_id_val)
    if not user_settings_obj:
        user_settings_obj = UserSettings(telegram_id=telegram_id_val, notification_settings=settings_val)
        session.add(user_settings_obj)
    else:
        user_settings_obj.notification_settings = settings_val
    await session.commit()

    user_specific_settings.notification_settings = settings_val
    USER_SETTINGS_CACHE[telegram_id_val] = user_specific_settings

    settings_messages_map = {
        NotificationSetting.ALL: get_text("notify_all_set", language),
        NotificationSetting.JOIN_OFF: get_text("notify_join_off_set", language),
        NotificationSetting.LEAVE_OFF: get_text("notify_leave_off_set", language),
        NotificationSetting.NONE: get_text("notify_none_set", language),
    }
    await message.reply(settings_messages_map[settings_val])

@settings_router.message(Command("notify_all"))
async def notify_all_cmd(message: Message, session: AsyncSession, language: str, user_specific_settings: UserSpecificSettings):
    await set_notification_settings_command(message, NotificationSetting.ALL, session, language, user_specific_settings)

@settings_router.message(Command("notify_join_off"))
async def notify_join_off_cmd(message: Message, session: AsyncSession, language: str, user_specific_settings: UserSpecificSettings):
    await set_notification_settings_command(message, NotificationSetting.JOIN_OFF, session, language, user_specific_settings)

@settings_router.message(Command("notify_leave_off"))
async def notify_leave_off_cmd(message: Message, session: AsyncSession, language: str, user_specific_settings: UserSpecificSettings):
    await set_notification_settings_command(message, NotificationSetting.LEAVE_OFF, session, language, user_specific_settings)

@settings_router.message(Command("notify_none"))
async def notify_none_cmd(message: Message, session: AsyncSession, language: str, user_specific_settings: UserSpecificSettings):
    await set_notification_settings_command(message, NotificationSetting.NONE, session, language, user_specific_settings)

async def update_mute_settings_db_and_cache(session: AsyncSession, telegram_id: int, user_specific_settings: UserSpecificSettings):
    user_settings_obj = await session.get(UserSettings, telegram_id)
    muted_users_str_val = ",".join(sorted(list(user_specific_settings.muted_users_set)))
    if not user_settings_obj:
        user_settings_obj = UserSettings(
            telegram_id=telegram_id,
            muted_users=muted_users_str_val,
            mute_all=user_specific_settings.mute_all_flag
        )
        session.add(user_settings_obj)
    else:
        user_settings_obj.muted_users = muted_users_str_val
        user_settings_obj.mute_all = user_specific_settings.mute_all_flag
    await session.commit()
    USER_SETTINGS_CACHE[telegram_id] = user_specific_settings


async def update_mute_user_list(session: AsyncSession, telegram_id: int, username_to_process: str, action: str, user_specific_settings: UserSpecificSettings):
    if action == "mute":
        user_specific_settings.muted_users_set.add(username_to_process)
    elif action == "unmute":
        user_specific_settings.muted_users_set.discard(username_to_process)
    await update_mute_settings_db_and_cache(session, telegram_id, user_specific_settings)

async def set_mute_all_state(session: AsyncSession, telegram_id: int, mute_all_flag: bool, user_specific_settings: UserSpecificSettings):
    user_specific_settings.mute_all_flag = mute_all_flag
    if not mute_all_flag:
        user_specific_settings.muted_users_set.clear()
    await update_mute_settings_db_and_cache(session, telegram_id, user_specific_settings)


@settings_router.message(Command("mute"))
async def mute_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    args_val = command.args
    if not args_val or not args_val.startswith("user "):
        await message.reply(get_text("mute_prompt_user", language))
        return

    username_to_mute_val = args_val[len("user "):].strip()
    if not username_to_mute_val:
         await message.reply(get_text("mute_username_empty", language))
         return

    telegram_id_val = message.from_user.id
    was_already_muted = username_to_mute_val in user_specific_settings.muted_users_set

    if was_already_muted and not user_specific_settings.mute_all_flag:
        await message.reply(get_text("mute_already_muted", language, username=html.quote(username_to_mute_val)))
    else:
        await update_mute_user_list(session, telegram_id_val, username_to_mute_val, "mute", user_specific_settings)
        await message.reply(get_text("mute_now_muted", language, username=html.quote(username_to_mute_val)))

@settings_router.message(Command("unmute"))
async def unmute_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    args_val = command.args
    if not args_val or not args_val.startswith("user "):
        await message.reply(get_text("unmute_prompt_user", language))
        return

    username_to_unmute_val = args_val[len("user "):].strip()
    if not username_to_unmute_val:
         await message.reply(get_text("mute_username_empty", language))
         return

    telegram_id_val = message.from_user.id
    was_muted = username_to_unmute_val in user_specific_settings.muted_users_set

    if was_muted or user_specific_settings.mute_all_flag:
        await update_mute_user_list(session, telegram_id_val, username_to_unmute_val, "unmute", user_specific_settings)
        await message.reply(get_text("unmute_now_unmuted", language, username=html.quote(username_to_unmute_val)))
    else:
        await message.reply(get_text("unmute_not_in_list", language, username=html.quote(username_to_unmute_val)))


@settings_router.message(Command("mute_all"))
async def mute_all_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    await set_mute_all_state(session, message.from_user.id, True, user_specific_settings)
    await message.reply(get_text("mute_all_enabled", language))

@settings_router.message(Command("unmute_all"))
async def unmute_all_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    await set_mute_all_state(session, message.from_user.id, False, user_specific_settings)
    await message.reply(get_text("unmute_all_disabled", language))

@settings_router.message(Command("toggle_noon"))
async def toggle_noon_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    telegram_id = message.from_user.id

    if not user_specific_settings.teamtalk_username or not user_specific_settings.not_on_online_confirmed:
        await message.reply(get_text("noon_not_configured", language))
        return

    new_enabled_status = not user_specific_settings.not_on_online_enabled

    db_user_settings = await session.get(UserSettings, telegram_id)
    if db_user_settings:
        db_user_settings.not_on_online_enabled = new_enabled_status
        await session.commit()

        user_specific_settings.not_on_online_enabled = new_enabled_status
        USER_SETTINGS_CACHE[telegram_id] = user_specific_settings

        reply_key = "noon_toggled_enabled" if new_enabled_status else "noon_toggled_disabled"
        reply_text = get_text(reply_key, language, tt_username=html.quote(user_specific_settings.teamtalk_username))
        logger.info(f"User {telegram_id} toggled 'not on online' to {new_enabled_status} for TT user {user_specific_settings.teamtalk_username}")
    else:
        reply_text = get_text("noon_error_updating", language)
        logger.error(f"Could not find UserSettings for {telegram_id} during toggle_noon.")

    await message.reply(reply_text)

@settings_router.message(Command("my_noon_status"))
async def my_noon_status_command_handler(
    message: Message,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not user_specific_settings.teamtalk_username or not user_specific_settings.not_on_online_confirmed:
        reply_text = get_text("noon_status_not_configured", language)
    else:
        status_key_en = "noon_status_enabled_en" if user_specific_settings.not_on_online_enabled else "noon_status_disabled_en"
        status_key_ru = "noon_status_enabled_ru" if user_specific_settings.not_on_online_enabled else "noon_status_disabled_ru"
        reply_text = get_text(
            "noon_status_report",
            language,
            status=get_text(status_key_en, "en"), 
            status_ru=get_text(status_key_ru, "ru"),
            tt_username=html.quote(user_specific_settings.teamtalk_username)
        )
    await message.reply(reply_text)


admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())

@admin_router.message(Command("kick"))
async def kick_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await show_user_buttons(message, "kick", language, tt_instance)

@admin_router.message(Command("ban"))
async def ban_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await show_user_buttons(message, "ban", language, tt_instance)


async def _process_id_action(user_id_val: int, user_nickname_val: str, language: str) -> str:
    return get_text("callback_user_id_info", language, user_nickname=html.quote(user_nickname_val), user_id=user_id_val)

async def _process_kick_action(
    user_id_val: int,
    user_nickname_val: str,
    tt_instance: TeamTalkInstance,
    language: str,
    admin_tg_id: int
) -> str:
    try:
        user_to_act_on = tt_instance.server.get_user(user_id_val)
        if user_to_act_on:
            user_to_act_on.kick(from_server=True)
            logger.info(f"Admin {admin_tg_id} kicked user {user_nickname_val} ({user_id_val})")
            return get_text("callback_user_kicked", language, user_nickname=html.quote(user_nickname_val))
        return get_text("callback_user_not_found_anymore", language)
    except Exception as e:
        logger.error(f"Error kicking user {user_nickname_val} ({user_id_val}): {e}")
        return get_text("callback_error_action_user", language, action="kick", action_ru=get_text("callback_action_kick_gerund_ru", "ru"), user_nickname=html.quote(user_nickname_val), error=str(e))

async def _process_ban_action(
    user_id_val: int,
    user_nickname_val: str,
    tt_instance: TeamTalkInstance,
    language: str,
    admin_tg_id: int
) -> str:
    try:
        user_to_act_on = tt_instance.server.get_user(user_id_val)
        if user_to_act_on:
            user_to_act_on.ban(from_server=True)
            user_to_act_on.kick(from_server=True)
            logger.info(f"Admin {admin_tg_id} banned user {user_nickname_val} ({user_id_val})")
            return get_text("callback_user_banned_kicked", language, user_nickname=html.quote(user_nickname_val))
        return get_text("callback_user_not_found_anymore", language)
    except Exception as e:
        logger.error(f"Error banning user {user_nickname_val} ({user_id_val}): {e}")
        return get_text("callback_error_action_user", language, action="ban", action_ru=get_text("callback_action_ban_gerund_ru", "ru"), user_nickname=html.quote(user_nickname_val), error=str(e))

USER_ACTION_CALLBACK_HANDLERS = {
    "id": _process_id_action,
    "kick": _process_kick_action,
    "ban": _process_ban_action,
}

@callback_router.callback_query(F.data.startswith("id:") | F.data.startswith("kick:") | F.data.startswith("ban:"))
async def process_user_selection(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await callback_query.answer()

    try:
        action_val, user_id_str_val, user_nickname_val = callback_query.data.split(":", 2)
        user_id_val = int(user_id_str_val)
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format: {callback_query.data}")
        await callback_query.message.edit_text(get_text("callback_invalid_data", language))
        return

    if not tt_instance:
         await callback_query.message.edit_text(get_text("tt_bot_not_connected", language))
         return

    reply_text_val = get_text("callback_unknown_action", language)
    handler = USER_ACTION_CALLBACK_HANDLERS.get(action_val)

    if handler:
        if action_val in ["kick", "ban"]:
            if not await is_admin(session, callback_query.from_user.id):
                await callback_query.answer(get_text("callback_no_permission", language), show_alert=True)
                return
            try:
                reply_text_val = await handler(user_id_val, user_nickname_val, tt_instance, language, callback_query.from_user.id)
            except Exception as e:
                logger.error(f"Error in {action_val} handler for {user_nickname_val}: {e}")
                reply_text_val = get_text("callback_error_find_user_tt", language)
        elif action_val == "id":
            reply_text_val = await handler(user_id_val, user_nickname_val, language)
    else:
         logger.warning(f"Unhandled action '{action_val}' in callback query.")

    await callback_query.message.edit_text(reply_text_val, reply_markup=None)


@callback_router.callback_query(F.data.startswith("toggle_ignore_user:"))
async def process_toggle_ignore_user(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    telegram_id_val = callback_query.from_user.id

    try:
        _, tt_username_to_toggle_val, nickname_from_callback_val = callback_query.data.split(":", 2)
        tt_username_to_toggle_val = tt_username_to_toggle_val.strip()
        nickname_from_callback_val = nickname_from_callback_val.strip()
    except ValueError:
        logger.error(f"Invalid callback data for toggle_ignore_user: {callback_query.data} from user {telegram_id_val}")
        await callback_query.answer(get_text("toggle_ignore_error_processing", language), show_alert=True)
        return

    if not tt_username_to_toggle_val:
        logger.error(f"Empty username in toggle_ignore_user callback: {callback_query.data} from user {telegram_id_val}")
        await callback_query.answer(get_text("toggle_ignore_error_empty_username", language), show_alert=True)
        return

    if user_specific_settings.mute_all_flag:
        if tt_username_to_toggle_val in user_specific_settings.muted_users_set:
            user_specific_settings.muted_users_set.discard(tt_username_to_toggle_val)
        else:
            user_specific_settings.muted_users_set.add(tt_username_to_toggle_val)
    else:
        if tt_username_to_toggle_val in user_specific_settings.muted_users_set:
            user_specific_settings.muted_users_set.discard(tt_username_to_toggle_val)
        else:
            user_specific_settings.muted_users_set.add(tt_username_to_toggle_val)

    await update_mute_settings_db_and_cache(session, telegram_id_val, user_specific_settings)

    user_is_now_effectively_ignored_val = False
    if user_specific_settings.mute_all_flag:
        user_is_now_effectively_ignored_val = tt_username_to_toggle_val not in user_specific_settings.muted_users_set
    else:
        user_is_now_effectively_ignored_val = tt_username_to_toggle_val in user_specific_settings.muted_users_set

    feedback_key = "toggle_ignore_now_ignored" if user_is_now_effectively_ignored_val else "toggle_ignore_no_longer_ignored"
    feedback_msg_for_answer_val = get_text(feedback_key, language, nickname=html.quote(nickname_from_callback_val))

    button_display_nickname_new_val = html.quote(nickname_from_callback_val)
    button_text_new_val = get_text("toggle_ignore_button_text", language, nickname=button_display_nickname_new_val)
    callback_data_new_val = f"toggle_ignore_user:{tt_username_to_toggle_val}:{nickname_from_callback_val}"

    new_keyboard_val = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text_new_val, callback_data=callback_data_new_val)]
    ])

    try:
        await callback_query.message.edit_reply_markup(reply_markup=new_keyboard_val)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info(f"Button markup for {nickname_from_callback_val} was not modified, as expected for static button text.")
        else:
            logger.error(f"TelegramBadRequest editing ignore button for {nickname_from_callback_val}: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing ignore button for {nickname_from_callback_val}: {e}")

    try:
        await callback_query.answer(text=feedback_msg_for_answer_val, show_alert=False)
    except TelegramAPIError as e:
        logger.warning(f"Could not send feedback answer for toggle_ignore_user for {nickname_from_callback_val}: {e}")


async def show_user_buttons(message: Message, command_type: str, language: str, tt_instance: TeamTalkInstance | None):
    if not tt_instance:
        await message.reply(get_text("tt_bot_not_connected", language))
        return

    try:
        users_list = tt_instance.server.get_users()
    except Exception as e:
        logger.error(f"Failed to get users from TT for {command_type}: {e}")
        await message.reply(get_text("tt_error_getting_users", language))
        return

    if not users_list:
        await message.reply(get_text("show_users_no_users_online", language))
        return

    builder = InlineKeyboardBuilder()
    my_user_id_val = tt_instance.getMyUserID()
    for user_obj in users_list:
        if user_obj.id == my_user_id_val:
            continue
        user_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or get_text("who_user_unknown", language)
        callback_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or "unknown"
        builder.button(text=html.quote(user_nickname_val), callback_data=f"{command_type}:{user_obj.id}:{callback_nickname_val[:30]}")

    if not builder._markup:
         await message.reply(get_text("show_users_no_other_users_online", language))
         return

    builder.adjust(2)
    command_text_key_map = {
        "id": "show_users_select_id",
        "kick": "show_users_select_kick",
        "ban": "show_users_select_ban"
    }
    command_text_key = command_text_key_map.get(command_type, "show_users_select_default")
    await message.reply(get_text(command_text_key, language), reply_markup=builder.as_markup())


async def send_long_tt_reply(reply_method: Callable, text: str, max_len_bytes: int = 511):
    if not text:
        return

    parts_to_send_list = []
    remaining_text_val = text

    while remaining_text_val:
        if len(remaining_text_val.encode("utf-8")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text_val)
            remaining_text_val = ""
            break

        current_chunk_bytes_val = 0
        possible_split_point_val = -1
        temp_buffer_val = ""

        for i, char_code_val in enumerate(remaining_text_val):
            char_bytes_val = char_code_val.encode("utf-8")

            if current_chunk_bytes_val + len(char_bytes_val) > max_len_bytes:
                if possible_split_point_val > 0 :
                    final_chunk_str_val = temp_buffer_val[:possible_split_point_val]
                    parts_to_send_list.append(final_chunk_str_val)
                    remaining_text_val = temp_buffer_val[possible_split_point_val:].lstrip() + remaining_text_val[i:]
                else:
                    parts_to_send_list.append(temp_buffer_val)
                    remaining_text_val = remaining_text_val[i:]
                break

            temp_buffer_val += char_code_val
            current_chunk_bytes_val += len(char_bytes_val)

            if char_code_val == "\n" or char_code_val == " ":
                possible_split_point_val = len(temp_buffer_val)

            if i == len(remaining_text_val) - 1:
                parts_to_send_list.append(temp_buffer_val)
                remaining_text_val = ""
                break
        else:
            if temp_buffer_val:
                 parts_to_send_list.append(temp_buffer_val)
            remaining_text_val = ""

    for part_idx_val, part_to_send_str_val in enumerate(parts_to_send_list):
        if part_to_send_str_val.strip():
            reply_method(part_to_send_str_val)
            logger.debug(f"Sent part {part_idx_val + 1}/{len(parts_to_send_list)} of help message, length {len(part_to_send_str_val.encode('utf-8'))} bytes.")
            if part_idx_val < len(parts_to_send_list) - 1:
                await asyncio.sleep(0.3)

@catch_all_router.message()
async def handle_unknown_command(message: Message, language: str):
    if not message.text:
        return
    logger.info(f"Received unknown message from {message.from_user.id}: {message.text[:50]}")
    await message.reply(get_text("unknown_command", language))

@tt_bot.event
async def on_ready():
    global current_tt_instance, login_complete_time
    server_info_obj = pytalk.TeamTalkServerInfo(
        config["HOSTNAME"], config["PORT"], config["PORT"],
        config["USERNAME"], config["PASSWORD"], encrypted=config["ENCRYPTED"], nickname=config["NICKNAME"]
    )
    try:
        login_complete_time = None
        await tt_bot.add_server(server_info_obj)
        logger.info(f"Initiated connection process for server: {config['HOSTNAME']}.")
    except Exception as e:
        logger.error(f"Error initiating server connection in on_ready: {e}")
        asyncio.create_task(_reconnect(None))

@tt_bot.event
async def on_my_login(server: PytalkServer) -> None:
    global current_tt_instance, login_complete_time
    tt_instance_val = server.teamtalk_instance
    current_tt_instance = tt_instance_val
    login_complete_time = None
    logger.info(f"Successfully logged in to server: {ttstr(tt_instance_val.server.get_properties().server_name)}")
    try:
        channel_id_or_path_val = config["CHANNEL"]
        channel_id_val = -1
        if channel_id_or_path_val.isdigit():
            channel_id_val = int(channel_id_or_path_val)
        else:
            try:
                channel_obj_val = tt_instance_val.get_channel_from_path(channel_id_or_path_val)
                if channel_obj_val:
                    channel_id_val = channel_obj_val.id
                else:
                    logger.error(f"Channel path '{channel_id_or_path_val}' not found during login.")
            except Exception as path_e:
                 logger.error(f"Error resolving channel path '{channel_id_or_path_val}' during login: {path_e}")

        if channel_id_val != -1:
            logger.info(f"Attempting to join channel: {config['CHANNEL']} (Resolved ID: {channel_id_val})")
            tt_instance_val.join_channel_by_id(channel_id_val, password=config["CHANNEL_PASSWORD"])
            await asyncio.sleep(1)
        else:
            logger.warning(f"Could not resolve channel '{config['CHANNEL']}' to an ID during login. Will attempt later if needed.")

        tt_instance_val.change_status(UserStatusMode.ONLINE, config["STATUS_TEXT"])
        logger.info(f"Status set to: {config['STATUS_TEXT']}")
        login_complete_time = datetime.utcnow()
        logger.info(f"Login sequence complete at {login_complete_time}.")

    except Exception as e:
        logger.error(f"Error during on_my_login (joining channel/setting status): {e}")
        if tt_instance_val:
            asyncio.create_task(_rejoin_channel(tt_instance_val))

async def _reconnect(tt_instance_val: TeamTalkInstance | None):
    global current_tt_instance, login_complete_time
    if current_tt_instance:
        logger.info("Reconnect already in progress or instance exists, skipping new task.")
        return
    logger.info("Starting reconnection process...")
    current_tt_instance = None
    login_complete_time = None
    await asyncio.sleep(5)
    while True:
        try:
            logger.info("Attempting to re-add server via on_ready logic...")
            await on_ready()
            await asyncio.sleep(10)

            if current_tt_instance and current_tt_instance.connected and current_tt_instance.logged_in:
                 logger.info("Reconnection successful.")
                 break
            logger.warning("Reconnection attempt failed (instance not ready/connected/logged in). Retrying in 15 seconds...")
            current_tt_instance = None
            login_complete_time = None

        except Exception as e:
            logger.error(f"Error during reconnection attempt: {e}. Retrying in 15 seconds...")
            current_tt_instance = None
            login_complete_time = None
        await asyncio.sleep(15)

async def _rejoin_channel(tt_instance_val: TeamTalkInstance):
    global login_complete_time
    if tt_instance_val is not current_tt_instance:
        logger.warning("Rejoin channel called for an outdated/inactive instance. Aborting.")
        return

    logger.info("Starting channel rejoin process...")
    await asyncio.sleep(2)
    attempts_val = 0
    max_attempts_val = 3

    while True:
        if not current_tt_instance or not current_tt_instance.connected or not current_tt_instance.logged_in:
             logger.warning("Not connected/logged in during rejoin attempt. Aborting rejoin and ensuring reconnect is triggered.")
             if not current_tt_instance:
                 login_complete_time = None
                 asyncio.create_task(_reconnect(None))
             return

        attempts_val += 1
        try:
            channel_id_or_path_val = config["CHANNEL"]
            channel_id_val = -1
            channel_name_val = ""
            try:
                if channel_id_or_path_val.isdigit():
                    channel_id_val = int(channel_id_or_path_val)
                    channel_obj_val = tt_instance_val.get_channel(channel_id_val)
                    channel_name_val = ttstr(channel_obj_val.name) if channel_obj_val else f"ID {channel_id_val}"
                else:
                    channel_obj_val = tt_instance_val.get_channel_from_path(channel_id_or_path_val)
                    if channel_obj_val:
                        channel_id_val = channel_obj_val.id
                        channel_name_val = ttstr(channel_obj_val.name)
                    else:
                        raise ValueError(f"Channel path '{channel_id_or_path_val}' not found")
            except Exception as chan_e:
                 logger.error(f"Error resolving channel '{channel_id_or_path_val}' during rejoin (Attempt {attempts_val}): {chan_e}. Retrying...")
                 await asyncio.sleep(5)
                 continue

            logger.info(f"Attempting to rejoin channel: {channel_name_val} (ID: {channel_id_val}) (Attempt {attempts_val})")
            tt_instance_val.join_channel_by_id(channel_id_val, password=config["CHANNEL_PASSWORD"])

            await asyncio.sleep(1)
            current_channel_id_val = tt_instance_val.getMyChannelID()
            if current_channel_id_val == channel_id_val:
                logger.info(f"Rejoined channel {channel_name_val} successfully.")
                break
            logger.warning(f"Failed to rejoin channel {channel_name_val}. Current channel ID: {current_channel_id_val}. Retrying...")

        except Exception as e:
            logger.error(f"Error during channel rejoin loop (Attempt {attempts_val}): {e}. Retrying in 3 seconds...")

        if attempts_val >= max_attempts_val:
            logger.warning(f"Failed to rejoin channel after {max_attempts_val} attempts. Waiting 20 seconds before trying again.")
            await asyncio.sleep(20)
            attempts_val = 0
        else:
            await asyncio.sleep(3)

@tt_bot.event
async def on_my_connection_lost(server: PytalkServer) -> None:
    global current_tt_instance, login_complete_time
    logger.warning("Connection lost (possibly kicked from server). Attempting to reconnect...")
    current_tt_instance = None
    login_complete_time = None
    asyncio.create_task(_reconnect(None))

@tt_bot.event
async def on_my_kicked_from_channel(channel_obj: PytalkChannel) -> None:
    global current_tt_instance, login_complete_time
    tt_instance_val = current_tt_instance

    if not tt_instance_val:
        logger.error("Kicked from channel/server, but current_tt_instance is None. Cannot process.")
        login_complete_time = None
        asyncio.create_task(_reconnect(None))
        return

    try:
        channel_id_val = channel_obj.id if channel_obj else -1

        if channel_id_val == 0:
            logger.warning("Kicked from server (received channel ID 0). Attempting to reconnect...")
            current_tt_instance = None
            login_complete_time = None
            asyncio.create_task(_reconnect(None))
        elif channel_id_val > 0:
            channel_name_val = ttstr(channel_obj.name) if channel_obj else "Unknown Channel"
            logger.warning(f"Kicked from channel {channel_name_val} (ID: {channel_id_val}). Attempting to rejoin...")
            asyncio.create_task(_rejoin_channel(tt_instance_val))
        else:
            logger.error(f"Received unexpected kick event with channel_obj ID: {channel_id_val}. Attempting full reconnect.")
            current_tt_instance = None
            login_complete_time = None
            asyncio.create_task(_reconnect(None))

    except Exception as e:
        channel_id_for_log_val = "unknown"
        if "channel_id_val" in locals():
            channel_id_for_log_val = channel_id_val
        logger.error(f"Error handling on_my_kicked_from_channel (ID: {channel_id_for_log_val}): {e}")
        current_tt_instance = None
        login_complete_time = None
        asyncio.create_task(_reconnect(None))

@tt_bot.event
async def on_message(message: TeamTalkMessage) -> None:
    if not current_tt_instance or message.from_id == current_tt_instance.getMyUserID() or message.type != 1:
        return

    sender_username_val = ttstr(message.user.username)
    message_content_val = message.content

    logger.info(f"Received private message from {sender_username_val}: {message_content_val[:100]}")

    async with SessionFactory() as session:
        admin_lang = "en"
        if config.get("TG_ADMIN_CHAT_ID"):
            admin_settings = USER_SETTINGS_CACHE.get(config["TG_ADMIN_CHAT_ID"])
            if admin_settings:
                admin_lang = admin_settings.language
        
        if message_content_val.startswith("/sub"):
            await handle_tt_subscribe_command(message, session, admin_lang)
        elif message_content_val.startswith("/unsub"):
            await handle_tt_unsubscribe_command(message, session, admin_lang)
        elif message_content_val.startswith("/add_admin"):
            await handle_tt_add_admin_command(message, session, admin_lang)
        elif message_content_val.startswith("/remove_admin"):
            await handle_tt_remove_admin_command(message, session, admin_lang)
        elif message_content_val.strip().lower() == "/not on online":
            await handle_tt_not_on_online_command(message, session, admin_lang)
        elif message_content_val.startswith("/help"):
            await send_help_message_tt(message, admin_lang)
        elif message_content_val.startswith("/"):
            reply_text_val = get_text("tt_unknown_command", admin_lang)
            message.reply(reply_text_val)
            logger.warning(f"Received unknown TT command from {sender_username_val}: {message_content_val}")
        elif config.get("TG_ADMIN_CHAT_ID") and tg_bot_message:
            await forward_tt_message_to_telegram(
                message=message,
                server_name_conf=config["SERVER_NAME"],
                sender_nickname=ttstr(message.user.nickname),
                message_text=message_content_val,
                admin_chat_id=config["TG_ADMIN_CHAT_ID"],
                admin_language=admin_lang,
                tt_instance_for_check=current_tt_instance
            )

async def forward_tt_message_to_telegram(
    message: TeamTalkMessage,
    server_name_conf: str | None,
    sender_nickname: str,
    message_text: str,
    admin_chat_id: int,
    admin_language: str,
    tt_instance_for_check: TeamTalkInstance | None = None
):
    tt_instance_val = message.teamtalk_instance
    server_name_val = "Unknown Server"
    if tt_instance_val and tt_instance_val.connected:
         try:
             server_name_val = server_name_conf or ttstr(tt_instance_val.server.get_properties().server_name)
         except Exception as e:
             logger.error(f"Could not get server name from TT instance: {e}")

    sender_display_val = sender_nickname or ttstr(message.user.username) or get_text("who_user_unknown", admin_language)

    text_val = get_text("tt_forward_message_text", admin_language,
                        server_name=html.quote(server_name_val),
                        sender_display=html.quote(sender_display_val),
                        message_text=html.quote(message_text))

    asyncio.create_task(send_telegram_message(
        config["TG_BOT_MESSAGE_TOKEN"],
        admin_chat_id,
        text_val,
        language=admin_language,
        reply_tt=message.reply,
        tt_instance_for_check=tt_instance_for_check
    ))

async def handle_tt_subscribe_command(message: TeamTalkMessage, session: AsyncSession, language: str):
    try:
        token_val = await create_deeplink(session, "subscribe")
        bot_info_val = await tg_bot_event.get_me()
        deeplink_val = f"https://t.me/{bot_info_val.username}?start={token_val}"
        reply_text_val = get_text("tt_subscribe_deeplink_text", language, deeplink_url=deeplink_val)
        message.reply(reply_text_val)
        logger.info(f"Generated subscribe deeplink {token_val} for TT user {ttstr(message.user.username)}")
    except Exception as e:
        logger.error(f"Error processing TT subscription for {ttstr(message.user.username)}: {e}")
        message.reply(get_text("tt_subscribe_error", language))

async def handle_tt_unsubscribe_command(message: TeamTalkMessage, session: AsyncSession, language: str):
    try:
        token_val = await create_deeplink(session, "unsubscribe")
        bot_info_val = await tg_bot_event.get_me()
        deeplink_val = f"https://t.me/{bot_info_val.username}?start={token_val}"
        reply_text_val = get_text("tt_unsubscribe_deeplink_text", language, deeplink_url=deeplink_val)
        message.reply(reply_text_val)
        logger.info(f"Generated unsubscribe deeplink {token_val} for TT user {ttstr(message.user.username)}")
    except Exception as e:
        logger.error(f"Error processing TT unsubscription for {ttstr(message.user.username)}: {e}")
        message.reply(get_text("tt_unsubscribe_error", language))

async def handle_tt_add_admin_command(message: TeamTalkMessage, session: AsyncSession, language: str):
    sender_username_val = ttstr(message.user.username)
    if not config["ADMIN_USERNAME"] or sender_username_val != config["ADMIN_USERNAME"]:
        logger.warning(f"Unauthorized /add_admin attempt by TT user {sender_username_val}.")
        message.reply(get_text("tt_admin_cmd_no_permission", language))
        return

    try:
        parts_list = message.content.split()
        if len(parts_list) < 2:
            message.reply(get_text("tt_add_admin_prompt_ids", language))
            return

        telegram_ids_to_add_list = parts_list[1:]
        added_count_val = 0
        errors_list = []
        for telegram_id_str_val in telegram_ids_to_add_list:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await add_admin(session, telegram_id_val):
                    added_count_val += 1
                    logger.info(f"Admin {telegram_id_val} added by TT user {sender_username_val}")
                else:
                    errors_list.append(get_text("tt_add_admin_error_already_admin", language, telegram_id=telegram_id_val))
            else:
                errors_list.append(get_text("tt_add_admin_error_invalid_id", language, telegram_id_str=telegram_id_str_val))

        reply_parts_list = []
        if added_count_val > 0:
            reply_parts_list.append(get_text("tt_add_admin_success", language, count=added_count_val))
        if errors_list:
            reply_parts_list.append(get_text("tt_admin_errors_header", language) + "\n- ".join(errors_list))

        message.reply("\n".join(reply_parts_list) if reply_parts_list else get_text("tt_admin_no_valid_ids", language))

    except Exception as e:
        logger.error(f"Error processing /add_admin command from {sender_username_val}: {e}")
        message.reply(get_text("tt_admin_error_processing", language))

async def handle_tt_remove_admin_command(message: TeamTalkMessage, session: AsyncSession, language: str):
    sender_username_val = ttstr(message.user.username)
    if not config["ADMIN_USERNAME"] or sender_username_val != config["ADMIN_USERNAME"]:
        logger.warning(f"Unauthorized /remove_admin attempt by TT user {sender_username_val}.")
        message.reply(get_text("tt_admin_cmd_no_permission", language))
        return

    try:
        parts_list = message.content.split()
        if len(parts_list) < 2:
            message.reply(get_text("tt_remove_admin_prompt_ids", language))
            return

        telegram_ids_to_remove_list = parts_list[1:]
        removed_count_val = 0
        errors_list = []
        for telegram_id_str_val in telegram_ids_to_remove_list:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await remove_admin_db(session, telegram_id_val):
                    removed_count_val += 1
                    logger.info(f"Admin {telegram_id_val} removed by TT user {sender_username_val}")
                else:
                    errors_list.append(get_text("tt_remove_admin_error_not_found", language, telegram_id=telegram_id_val))
            else:
                errors_list.append(get_text("tt_add_admin_error_invalid_id", language, telegram_id_str=telegram_id_str_val))

        reply_parts_list = []
        if removed_count_val > 0:
            reply_parts_list.append(get_text("tt_remove_admin_success", language, count=removed_count_val))
        if errors_list:
            reply_parts_list.append(get_text("tt_admin_info_errors_header", language) + "\n- ".join(errors_list))

        message.reply("\n".join(reply_parts_list) if reply_parts_list else get_text("tt_admin_no_valid_ids", language))

    except Exception as e:
        logger.error(f"Error processing /remove_admin command from {sender_username_val}: {e}")
        message.reply(get_text("tt_admin_error_processing", language))

async def handle_tt_not_on_online_command(message: TeamTalkMessage, session: AsyncSession, language: str):
    sender_tt_username = ttstr(message.user.username)

    if message.content.strip().lower() != "/not on online":
        message.reply(get_text("tt_noon_usage", language))
        return

    try:
        token = await create_deeplink(
            session,
            action="confirm_not_on_online",
            payload=sender_tt_username,
            expected_telegram_id=None
        )
        bot_info = await tg_bot_event.get_me()
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"

        message.reply(get_text("tt_noon_confirm_deeplink_text", language, tt_username=sender_tt_username, deeplink_url=deeplink_url))
        logger.info(f"Generated 'not on online' confirmation deeplink {token} for TT user {sender_tt_username} (generic TG target)")
    except Exception as e:
        logger.error(f"Error processing TT /not on online for {sender_tt_username}: {e}")
        message.reply(get_text("tt_noon_error_processing", language))


async def send_help_message_tt(message: TeamTalkMessage, language: str):
    help_text_key = "help_text_ru" if language == "ru" else "help_text_en"
    help_text_val = get_text(help_text_key, language)
    await send_long_tt_reply(message.reply, help_text_val, max_len_bytes=511)

async def should_notify(telegram_id: int, user_username: str, event_type: str) -> bool:
    user_settings_val = USER_SETTINGS_CACHE.get(telegram_id)
    if not user_settings_val:
         logger.warning(f"Settings not found in cache for {telegram_id} during should_notify check.")
         return False

    notification_pref_val = user_settings_val.notification_settings
    mute_all_val = user_settings_val.mute_all_flag
    muted_users_set = user_settings_val.muted_users_set

    if notification_pref_val == NotificationSetting.NONE:
        return False
    if event_type == "join" and notification_pref_val == NotificationSetting.JOIN_OFF:
        return False
    if event_type == "leave" and notification_pref_val == NotificationSetting.LEAVE_OFF:
        return False

    if mute_all_val:
        return user_username in muted_users_set
    return user_username not in muted_users_set

async def send_join_leave_notification(
    event_type: str,
    user: TeamTalkUser,
    tt_instance: TeamTalkInstance
):
    server_name_val = config["SERVER_NAME"] or (ttstr(tt_instance.server.get_properties().server_name) if tt_instance and tt_instance.connected else "Unknown Server")
    user_nickname_val = ttstr(user.nickname) or ttstr(user.username) or "unknown user"
    user_username_val = ttstr(user.username)
    user_id_val = user.id

    if not user_username_val:
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname_val}, ID: {user_id_val}). Skipping notification.")
        return

    if config["GLOBAL_IGNORE_USERNAME"] and user_username_val == config["GLOBAL_IGNORE_USERNAME"]:
        logger.info(f"User {user_username_val} is globally ignored. Skipping {event_type} notification.")
        return

    async with SessionFactory() as session:
        subscribers_list = await get_all_subscribers(session)

    chat_ids_to_notify_list = []
    for chat_id_val in subscribers_list:
        if chat_id_val not in USER_SETTINGS_CACHE:
            async with SessionFactory() as temp_session:
                 await _async_load_user_settings(chat_id_val, temp_session)

        if await should_notify(chat_id_val, user_username_val, event_type):
            chat_ids_to_notify_list.append(chat_id_val)

    if not chat_ids_to_notify_list:
        logger.info(f"No subscribers to notify for {event_type} of user {user_username_val}.")
        return

    def text_gen(lang_code: str) -> str:
        key = "join_notification" if event_type == "join" else "leave_notification"
        return get_text(key, lang_code, user_nickname=html.quote(user_nickname_val), server_name=html.quote(server_name_val))

    def markup_gen(tt_user_username: str, tt_user_nickname: str, lang_code: str, recipient_tg_id: int) -> InlineKeyboardMarkup | None:
        button_display_nickname_val = html.quote(tt_user_nickname[:30])
        callback_data_val = f"toggle_ignore_user:{tt_user_username}:{tt_user_nickname[:30]}"
        button_text_val = get_text("toggle_ignore_button_text", lang_code, nickname=button_display_nickname_val)
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_text_val, callback_data=callback_data_val)]
        ])

    async with SessionFactory() as send_session:
        await send_telegram_messages(
            token=config["TG_EVENT_TOKEN"],
            chat_ids=chat_ids_to_notify_list,
            text_generator=text_gen,
            session=send_session,
            reply_markup_generator=markup_gen,
            tt_user_username_for_markup=user_username_val,
            tt_user_nickname_for_markup=user_nickname_val,
            tt_instance_for_check=tt_instance
        )
    logger.info(f"Prepared {event_type} notification for {user_username_val} ({user_id_val}) to {len(chat_ids_to_notify_list)} subscribers.")


@tt_bot.event
async def on_user_login(user: TeamTalkUser) -> None:
    global login_complete_time
    server_obj = user.server
    tt_instance_val = server_obj.teamtalk_instance

    if login_complete_time is None or datetime.utcnow() < login_complete_time + timedelta(seconds=2):
        logger.debug(f"Ignoring potential initial sync join for {ttstr(user.username)} ({user.id}).")
        return
    await send_join_leave_notification("join", user, tt_instance_val)

@tt_bot.event
async def on_user_logout(user: TeamTalkUser) -> None:
    await send_join_leave_notification("leave", user, user.server.teamtalk_instance)

async def set_commands(bot_obj: Bot):
    commands_list = [
        BotCommand(command="who", description="Show online users"),
        BotCommand(command="id", description="Get user ID (buttons)"),
        BotCommand(command="kick", description="Kick user (admin, buttons)"),
        BotCommand(command="ban", description="Ban user (admin, buttons)"),
        BotCommand(command="cl", description="Change language (en/ru)"),
        BotCommand(command="notify_all", description="Enable all join/leave notifications"),
        BotCommand(command="notify_join_off", description="Disable join notifications"),
        BotCommand(command="notify_leave_off", description="Disable leave notifications"),
        BotCommand(command="notify_none", description="Disable all join/leave notifications"),
        BotCommand(command="start", description="Start bot or process deeplink"),
        BotCommand(command="mute", description="Mute notifications from a user (/mute user <name>)"),
        BotCommand(command="unmute", description="Unmute notifications from a user (/unmute user <name>)"),
        BotCommand(command="mute_all", description="Mute all users by default (except exceptions)"),
        BotCommand(command="unmute_all", description="Unmute all users by default (except muted)"),
        BotCommand(command="toggle_noon", description="Toggle 'not on online' silent notifications"),
        BotCommand(command="my_noon_status", description="Check 'not on online' status"),
        BotCommand(command="help", description="Show help message")
    ]
    try:
        await bot_obj.set_my_commands(commands=commands_list, scope=BotCommandScopeAllPrivateChats())
        logger.info("Bot commands updated successfully.")
    except TelegramAPIError as e:
        logger.error(f"Failed to set bot commands: {e}")

async def main():
    await init_db()
    await load_user_settings_to_cache(SessionFactory)
    await set_commands(tg_bot_event)

    dp = Dispatcher()

    dp.update.outer_middleware.register(DbSessionMiddleware(SessionFactory))
    dp.message.middleware(UserSettingsMiddleware())
    dp.callback_query.middleware(UserSettingsMiddleware())
    dp.update.outer_middleware.register(TeamTalkInstanceMiddleware(tt_bot))


    dp.include_router(user_commands_router)
    dp.include_router(settings_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(catch_all_router)

    logger.info("Starting Telegram bot polling and TeamTalk bot...")

    await tt_bot._async_setup_hook()

    try:
        await asyncio.gather(
            dp.start_polling(tg_bot_event, allowed_updates=dp.resolve_used_update_types()),
            tt_bot._start()
        )
    finally:
        logger.info("Shutting down bots...")
        await tg_bot_event.session.close()
        if tg_bot_message:
             await tg_bot_message.session.close()

        logger.info("Disconnecting TeamTalk instances...")
        for tt_instance_item in tt_bot.teamtalks:
            try:
                if tt_instance_item.logged_in:
                    tt_instance_item.logout()
                if tt_instance_item.connected:
                    tt_instance_item.disconnect()
                tt_instance_item.closeTeamTalk()
                logger.info(f"Closed TeamTalk instance for {tt_instance_item.server_info.host}")
            except Exception as e:
                logger.error(f"Error closing TeamTalk instance for {tt_instance_item.server_info.host}: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ValueError, KeyError) as ve:
        logger.critical(f"Configuration Error: {ve}. Please check your .env file or environment variables.")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred in main: {e}", exc_info=True)
    finally:
        logger.info("Application finished.")
