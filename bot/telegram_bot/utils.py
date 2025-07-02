import logging
import asyncio
import pytalk
from typing import Callable
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramBadRequest
from sqlalchemy.exc import SQLAlchemyError


from bot.config import app_config
from bot.database.crud import remove_subscriber, delete_user_data_fully
from bot.database.engine import SessionFactory
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.state import ONLINE_USERS_CACHE
from bot.core.languages import Language
from bot.constants import (
    DEFAULT_LANGUAGE,
)
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


async def _handle_telegram_api_error(error: TelegramAPIError, chat_id: int):
    """
    Handles specific Telegram API errors, performing actions like unsubscribing users
    or logging detailed error information.
    """
    if isinstance(error, TelegramForbiddenError):
        if "bot was blocked by the user" in str(error).lower() or "user is deactivated" in str(error).lower():
            # <<< ИЗМЕНЕНО: Обновляем лог, чтобы отразить полное удаление данных
            logger.warning(f"User {chat_id} blocked the bot or is deactivated. Deleting all user data...")
            try:
                async with SessionFactory() as session:
                    # <<< ИЗМЕНЕНО: Вызываем правильную, полную функцию удаления
                    success = await delete_user_data_fully(session, chat_id)
                if success:
                    # <<< ИЗМЕНЕНО: Обновляем лог
                    logger.info(f"Successfully deleted all data for blocked/deactivated user {chat_id}.")
                else:
                    logger.error(f"Failed to delete data for blocked/deactivated user {chat_id}, though an attempt was made.")
                # <<< УДАЛЕНО: pop из USER_SETTINGS_CACHE теперь происходит внутри delete_user_data_fully,
                # поэтому дублировать здесь не нужно.
            except SQLAlchemyError as db_err:
                logger.error(f"Failed to delete data for blocked/deactivated user {chat_id} from DB: {db_err}")
        else:
            logger.error(f"Telegram API Forbidden error for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramBadRequest):
        if "chat not found" in str(error).lower():
            logger.warning(f"Chat not found for TG ID {chat_id}. Assuming user is gone. Deleting all user data. Error: {error}")
            try:
                async with SessionFactory() as session:
                    delete_success = await delete_user_data_fully(session, chat_id)
                if delete_success:
                    logger.info(f"Successfully deleted all data for TG ID {chat_id} due to chat not found.")
                else:
                    logger.error(f"Failed to delete all data for TG ID {chat_id} after chat not found.")

                if USER_SETTINGS_CACHE.pop(chat_id, None): # Remove from cache regardless
                    logger.debug(f"Removed user {chat_id} from settings cache after chat not found.")
                else:
                    logger.debug(f"User {chat_id} was not in settings cache (or already removed) after chat not found.")
            except SQLAlchemyError as db_cleanup_err:
                logger.error(f"Exception during full data cleanup for TG ID {chat_id} (chat not found): {db_cleanup_err}")
        else:
            logger.error(f"Telegram API BadRequest (non 'chat not found') for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramAPIError): # Catch-all for other TelegramAPIError types
        logger.error(f"Unhandled Telegram API error for chat_id {chat_id}: {error}")

    # Non-TelegramAPIError exceptions are not handled by this function.
    # The calling function would need a separate except block for those if desired.


def _should_send_silently(chat_id: int, tt_user_is_online: bool) -> bool:
    """
    Checks if a message to a given chat_id should be sent silently based on
    NOON settings and the provided online status of their linked TeamTalk user.
    """
    recipient_settings = USER_SETTINGS_CACHE.get(chat_id)

    if (
        recipient_settings and
        recipient_settings.not_on_online_enabled and
        recipient_settings.not_on_online_confirmed and
        tt_user_is_online # Directly use the passed boolean
    ):
        logger.debug(f"Message to {chat_id} will be silent: linked user is online and NOON is enabled.")
        return True

    return False


async def send_telegram_message_individual(
    bot_instance: Bot,
    chat_id: int,
    language: str = DEFAULT_LANGUAGE,
    reply_markup: InlineKeyboardMarkup | None = None,
    tt_user_is_online: bool = False,
    **kwargs
) -> bool:
    send_silently = _should_send_silently(chat_id, tt_user_is_online)

    try:
        await bot_instance.send_message(
            chat_id=chat_id,
            reply_markup=reply_markup,
            disable_notification=send_silently,
            **kwargs # Pass kwargs directly
        )
        logger.debug(f"Message sent to {chat_id}. Silent: {send_silently}, kwargs used: {kwargs}")
        return True

    except TelegramAPIError as e:
        await _handle_telegram_api_error(e, chat_id)
        return False

    # Non-TelegramAPIError exceptions will propagate if not caught by the caller.
    # If they were to be caught here and also result in 'False', an outer try-except would be needed.
    # Based on current structure, only TelegramAPIError results in False from this function.


async def send_telegram_messages_to_list(
    bot_instance_to_use: Bot, # Теперь принимаем сам объект бота
    chat_ids: list[int],
    text_generator: Callable[[str], str], # Takes language code, returns text
        reply_markup_generator: Callable[[str, int], InlineKeyboardMarkup | None] | None = None
):
    """
    Sends messages to a list of chat_ids.
    Uses the provided bot_instance_to_use.
    """
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to send_telegram_messages_to_list.")
        return

    online_tt_usernames = {ttstr(user.username) for user in ONLINE_USERS_CACHE.values()}
    tasks_list = []
    for chat_id in chat_ids:
        user_settings = USER_SETTINGS_CACHE.get(chat_id)
        language = user_settings.language.value if user_settings else DEFAULT_LANGUAGE
        text = text_generator(language)

        current_reply_markup = None
        if reply_markup_generator:
            current_reply_markup = reply_markup_generator(
                language,
                chat_id
            )

        individual_tt_user_is_online = False
        if user_settings and user_settings.teamtalk_username:
            if user_settings.teamtalk_username in online_tt_usernames:
                individual_tt_user_is_online = True

        tasks_list.append(send_telegram_message_individual(
            bot_instance=bot_instance_to_use, # Теперь используется напрямую
            chat_id=chat_id,
            language=language,
            reply_markup=current_reply_markup,
            tt_user_is_online=individual_tt_user_is_online,
            text=text,
            parse_mode="HTML"
        ))
    await asyncio.gather(*tasks_list)