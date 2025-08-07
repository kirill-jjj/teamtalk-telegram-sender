"""Utility functions for creating and managing UI elements like paginated lists."""

from collections.abc import Awaitable, Callable
from gettext import NullTranslations
import logging
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message

from bot.constants import USERS_PER_PAGE

T = TypeVar("T")
logger = logging.getLogger(__name__)


def paginate_list(full_list: list[T], page: int, page_size: int = USERS_PER_PAGE) -> tuple[list[T], int, int]:
    """Paginates a given list.

    Args:
        full_list: The full list of items to paginate.
        page: The requested page number (0-indexed).
        page_size: The number of items per page.

    Returns:
        A tuple containing:
            - page_slice: The slice of the list for the current page.
            - total_pages: The total number of pages.
            - current_page_idx: The validated current page index.
    """
    total_items = len(full_list)
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    current_page_idx = max(0, min(page, total_pages - 1))

    start_index = current_page_idx * page_size
    end_index = start_index + page_size
    page_slice: list[T] = full_list[start_index:end_index]

    return page_slice, total_pages, current_page_idx


async def display_paginated_list(
    target: CallbackQuery | Message,
    bot: Bot,
    translator: NullTranslations,
    items: list[Any],
    page: int,
    title_text: str,
    empty_list_text: str,
    keyboard_factory: Callable[..., Awaitable[InlineKeyboardMarkup]],
    keyboard_factory_kwargs: dict[str, Any],
    page_size: int = USERS_PER_PAGE,
    server_host_for_display: str | None = None,
) -> None:
    """Displays or updates a paginated list in a Telegram message.

    Can send a new message or edit an existing one based on the target type.

    Args:
        target: The Aiogram CallbackQuery (to edit message) or Message (to send new message / get chat_id).
        bot: The Aiogram Bot instance.
        translator: The gettext NullTranslations object for localization.
        items: The full list of items to display.
        page: The current page number (0-indexed).
        title_text: The main title text for the message.
        empty_list_text: Text to display if the items list is empty.
        keyboard_factory: An async callable that returns an InlineKeyboardMarkup.
        keyboard_factory_kwargs: Additional keyword arguments for the keyboard_factory.
        page_size: Number of items per page.
        server_host_for_display: Optional server host string to append to the title.
    """
    _ = translator.gettext
    page_slice, total_pages, current_page_idx = paginate_list(items, page, page_size)

    message_parts = [title_text]
    if not items:
        message_parts.append(empty_list_text)

    page_indicator_text = _("Page {current_page}/{total_pages}").format(
        current_page=current_page_idx + 1, total_pages=total_pages
    )

    if server_host_for_display and " on {server_host}" not in message_parts[0]:  # SIM102 fix applied here
        message_parts[0] += _(" on {server_host}").format(server_host=server_host_for_display)

    message_parts.append(f"\n{page_indicator_text}")
    final_message_text = "\n".join(message_parts)

    keyboard_markup = await keyboard_factory(
        translator,
        page_items=page_slice,
        current_page=current_page_idx,
        total_pages=total_pages,
        **keyboard_factory_kwargs,
    )

    if isinstance(target, CallbackQuery) and isinstance(target.message, Message):
        # Edit existing message from callback query
        await safe_edit_text(
            message_to_edit=target.message,
            text=final_message_text,
            reply_markup=keyboard_markup,
            parse_mode="HTML",
            logger_instance=logger,
            log_context=f"display_paginated_list (edit) for {title_text}",
        )

    elif isinstance(target, Message):
        # Send new message
        try:
            await bot.send_message(
                chat_id=target.chat.id,
                text=final_message_text,
                reply_markup=keyboard_markup,
                parse_mode="HTML",
            )
        except TelegramAPIError:
            logger.exception(
                "TelegramAPIError sending new paginated list for '%s' to chat %s", title_text, target.chat.id
            )
    # The case `isinstance(target, CallbackQuery) and target.message is None` is considered unreachable
    # because all callback handlers that would call this function are decorated with `@ensure_message_context`,
    # which prevents execution if `query.message` is None.
    else:
        # This 'else' now catches cases where target is not a CallbackQuery with a message,
        # nor a direct Message object. This could be an improperly constructed CallbackQuery
        # (though unlikely if from Aiogram) or an unexpected type.
        logger.error(
            "Invalid target type or unexpected state for display_paginated_list for '%s'. Target type: %s",
            title_text,
            type(target).__name__,
        )
        if isinstance(target, CallbackQuery):
            try:
                await target.answer(_("Error displaying list."), show_alert=True)
            except TelegramAPIError:
                logger.exception("Failed to answer callback for invalid target type for %s", title_text)


async def safe_edit_text(
    message_to_edit: Message | InaccessibleMessage,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    *,  # Make disable_web_page_preview keyword-only
    disable_web_page_preview: bool | None = None,
    logger_instance: logging.Logger | None = None,
    log_context: str = "",
) -> bool:
    """Safely edits a message text, handling common Telegram API errors."""
    current_logger = logger_instance or logger
    context_for_log = f" ({log_context})" if log_context else ""

    if not isinstance(message_to_edit, Message):
        current_logger.warning("Attempted to edit an inaccessible message%s.", context_for_log)
        return False

    try:
        await message_to_edit.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            current_logger.exception("TelegramBadRequest editing message%s.", context_for_log)
            return False
        current_logger.debug(
            "Message not modified for %s (chat_id %s), skipping edit. Error: %s",
            log_context,
            message_to_edit.chat.id,
            e,
        )
        return True
    except TelegramAPIError:
        current_logger.exception("TelegramAPIError editing message%s.", context_for_log)
        return False
    else:
        return True
