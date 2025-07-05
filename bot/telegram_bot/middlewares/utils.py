import logging
from typing import TYPE_CHECKING
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError

if TYPE_CHECKING:
    pass # No specific type hints needed from sender.Application here yet

logger = logging.getLogger(__name__)

async def _send_error_response(
    event: TelegramObject,
    text: str,
    show_alert_for_callback: bool = True
) -> None:
    """
    Internal helper to send an error response based on event type.
    """
    if isinstance(event, Message):
        try:
            await event.reply(text)
        except TelegramAPIError as e:
            logger.error(f"TelegramAPIError replying to message in _send_error_response: {e}")
        except Exception as e:
            logger.error(f"Unexpected error replying to message in _send_error_response: {e}", exc_info=True)
    elif isinstance(event, CallbackQuery):
        try:
            await event.answer(text, show_alert=show_alert_for_callback)
        except TelegramAPIError as e:
            logger.error(f"TelegramAPIError answering callback query in _send_error_response: {e}")
        except Exception as e:
            logger.error(f"Unexpected error answering callback query in _send_error_response: {e}", exc_info=True)
    else:
        logger.warning(f"_send_error_response: Unhandled event type {type(event)}")
