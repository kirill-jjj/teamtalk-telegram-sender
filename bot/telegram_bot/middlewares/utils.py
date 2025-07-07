"""Utility functions for Telegram middlewares, such as sending error responses."""

import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

if TYPE_CHECKING:
    pass  # No specific type hints needed from sender.Application here yet

logger = logging.getLogger(__name__)


async def _send_error_response(event: TelegramObject, text: str, show_alert_for_callback: bool = True) -> None:
    """Internal helper to send an error response based on event type."""
    if isinstance(event, Message):
        try:
            await event.reply(text)
        except TelegramAPIError as e:
            logger.error("TelegramAPIError replying to message in _send_error_response: %s", e)
        except Exception as e:
            logger.exception("Unexpected error replying to message in _send_error_response: %s", e)
    elif isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=show_alert_for_callback)
        except TelegramAPIError as e:
            logger.error("TelegramAPIError answering callback query in _send_error_response: %s", e)
        except Exception as e:
            logger.exception("Unexpected error answering callback query in _send_error_response: %s", e)
    else:
        logger.warning("_send_error_response: Unhandled event type %s", type(event))
