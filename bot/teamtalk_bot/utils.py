import logging
import asyncio
from typing import Callable, TYPE_CHECKING # Добавь TYPE_CHECKING для подсказки типа
from aiogram.utils.formatting import Text, Bold

import pytalk
# УДАЛИ СЛЕДУЮЩУЮ СТРОКУ:
# from bot.teamtalk_bot import bot_instance as tt_bot_module

# УДАЛИ СЛЕДУЮЩИЕ СТРОКИ ИМПОРТА ГЛОБАЛЬНЫХ ЗАВИСИМОСТЕЙ (app_config, tg_bot_message, USER_SETTINGS_CACHE):
# from bot.config import app_config
# from bot.telegram_bot.bot_instances import tg_bot_message
# from bot.core.user_settings import USER_SETTINGS_CACHE
# from bot.core.utils import get_effective_server_name, get_tt_user_display_name # Оставь, но убедись, что они используют переданные параметры
from bot.language import get_translator
from bot.constants import (
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
    DEFAULT_LANGUAGE
)
from bot.telegram_bot.utils import send_telegram_message_individual
from bot.core.utils import get_effective_server_name, get_tt_user_display_name


from pytalk import TeamTalkServerInfo
from pytalk.instance import TeamTalkInstance, sdk
from pytalk.message import Message as TeamTalkMessage

# Добавь импорт Application для Type Hinting
if TYPE_CHECKING:
    from sender import Application
    from bot.teamtalk_bot.connection import TeamTalkConnection # Для подсказки типа connection

logger = logging.getLogger(__name__)
ttstr = sdk.ttstr

# Глобальная переменная RECONNECT_IN_PROGRESS также должна быть удалена
# и её логика перемещена в класс Application (если она нужна для предотвращения множественных реконнектов)
# Или, если она служит для конкретного инстанса, в TeamTalkConnection.
# Удаляем: RECONNECT_IN_PROGRESS = False


async def shutdown_tt_instance(instance: TeamTalkInstance) -> None: # Добавь Type Hint для возвращаемого значения
    """Safely shuts down a single TeamTalk instance."""
    # Эта функция сейчас не использует глобальных переменных, поэтому она может остаться как есть
    # Но если RECONNECT_IN_PROGRESS выше удалена, то она не должна быть глобальной
    # Эта функция вызывается из Application._on_shutdown_logic или Application._initiate_reconnect_for_connection
    # И ей не нужен "app" или "connection", только "instance".
    # Логика RECONNECT_IN_PROGRESS должна быть в Application._initiate_reconnect_for_connection
    try:
        # Ensure server_info and host are available for logging, provide default if not
        host_info = "Unknown Host"
        if hasattr(instance, 'server_info') and instance.server_info and hasattr(instance.server_info, 'host'):
            host_info = ttstr(instance.server_info.host)

        if instance.logged_in:
            logger.debug(f"Logging out from TT instance: {host_info}")
            instance.logout()
        if instance.connected:
            logger.debug(f"Disconnecting from TT instance: {host_info}")
            instance.disconnect()
        # Check for closeTeamTalk attribute as it might not always be present
        # (though in typical TeamTalkInstance it should be)
        if hasattr(instance, 'closeTeamTalk'):
            logger.debug(f"Closing TT instance: {host_info}")
            instance.closeTeamTalk()
        logger.info(f"Successfully shut down TT instance for host: {host_info}")
    except (pytalk.exceptions.TeamTalkException, TimeoutError, ConnectionError, OSError) as e:
        # Attempt to get host_info again in case it was not available before error
        host_info_err = "Unknown Host (during error)"
        if hasattr(instance, 'server_info') and instance.server_info and hasattr(instance.server_info, 'host'):
            host_info_err = ttstr(instance.server_info.host)
        logger.error(f"Error during TT instance shutdown for {host_info_err}: {e}", exc_info=True)

# Логика initiate_reconnect_task должна быть перемещена в метод класса Application
# УДАЛИ: initiate_reconnect_task
# УДАЛИ: _tt_reconnect

def _split_text_for_tt(text: str, max_len_bytes: int) -> list[str]:
    parts_to_send_list = []
    remaining_text = text

    while remaining_text:
        if len(remaining_text.encode("utf-8", errors="ignore")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text)
            break

        current_chunk_str = ""
        current_chunk_bytes_len = 0
        last_safe_split_index_in_chunk = -1
        last_safe_split_index_in_remaining = -1

        for i, char_code in enumerate(remaining_text):
            char_bytes = char_code.encode("utf-8", errors="ignore")
            char_bytes_len = len(char_bytes)

            if current_chunk_bytes_len + char_bytes_len > max_len_bytes:
                if last_safe_split_index_in_chunk != -1:
                    parts_to_send_list.append(current_chunk_str[:last_safe_split_index_in_chunk])
                    remaining_text = remaining_text[last_safe_split_index_in_remaining:].lstrip()
                else:
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text = remaining_text[i:].lstrip()
                break

            current_chunk_str += char_code
            current_chunk_bytes_len += char_bytes_len

            if char_code == '\n':
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1
            elif char_code == ' ':
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text) - 1:
                parts_to_send_list.append(current_chunk_str)
                remaining_text = ""
                break
        else:
            if current_chunk_str and not remaining_text:
                 logger.debug("_split_text_for_tt: Appending final chunk in else block, this might be redundant.")
                 parts_to_send_list.append(current_chunk_str)
            remaining_text = ""
    return parts_to_send_list


async def send_long_tt_reply(reply_method: Callable[[str], None], text: str, max_len_bytes: int = TT_MAX_MESSAGE_BYTES):
    """
    Splits a long text message into parts suitable for TeamTalk and sends them.
    Uses asyncio.to_thread for the potentially CPU-bound splitting logic.
    """
    if not text:
        return

    parts_to_send_list = await asyncio.to_thread(_split_text_for_tt, text, max_len_bytes)

    for part_idx, part_to_send_str in enumerate(parts_to_send_list):
        if part_to_send_str.strip():
            try:
                reply_method(part_to_send_str)
                logger.debug(f"Sent part {part_idx + 1}/{len(parts_to_send_list)} of TT message, length {len(part_to_send_str.encode('utf-8', errors='ignore'))} bytes.")
                if part_idx < len(parts_to_send_list) - 1:
                    await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
            except pytalk.exceptions.TeamTalkException as e:
                logger.error(f"Error sending part {part_idx + 1} of TT message: {e}")
                break


async def forward_tt_message_to_telegram_admin(
    message: TeamTalkMessage,
    app: "Application", # Добавь app как обязательный аргумент
    server_host_for_display: str # Добавь host, так как app_config больше не глобальный
):
    # Замени все использования app_config, tg_bot_message, USER_SETTINGS_CACHE
    # на app.app_config, app.tg_bot_message, app.user_settings_cache
    if not app.app_config.TG_ADMIN_CHAT_ID or not app.tg_bot_message:
        logger.debug("Telegram admin chat ID or message bot not configured. Skipping TT forward.")
        return

    admin_chat_id = app.app_config.TG_ADMIN_CHAT_ID
    admin_settings = app.user_settings_cache.get(admin_chat_id) # Используй app.user_settings_cache
    admin_language_code = admin_settings.language_code if admin_settings else DEFAULT_LANGUAGE

    translator = get_translator(admin_language_code)
    _ = translator.gettext

    # tt_instance = message.teamtalk_instance # Уже есть в message
    # server_name = get_effective_server_name(message.teamtalk_instance, _, app.app_config) # Передаем app.app_config
    # Вместо server_host_for_display можно использовать get_effective_server_name, если он более точен
    server_name_to_display = get_effective_server_name(message.teamtalk_instance, _, app.app_config)

    sender_display = get_tt_user_display_name(message.user, _)
    message_content = message.content

    content = Text(
        _("Message from server "), Bold(server_name_to_display), "\n", # Используем server_name_to_display
        _("From "), Bold(sender_display), ":\n\n",
        message_content
    )

    was_sent: bool = await send_telegram_message_individual(
        bot_instance=app.tg_bot_message, # Используй app.tg_bot_message
        chat_id=admin_chat_id,
        language=admin_language_code,
        app=app, # Передаем app
        **content.as_kwargs()
    )

    if was_sent:
        message.reply(_("Message sent to Telegram successfully."))
    else:
        message.reply(_("Failed to send message: {error}").format(error=_("Failed to deliver message to Telegram")))
