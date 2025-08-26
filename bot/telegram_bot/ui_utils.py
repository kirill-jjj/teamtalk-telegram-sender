"""Utility functions for creating and managing UI elements like paginated lists."""

from collections.abc import Awaitable, Callable
from gettext import NullTranslations
import logging
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
)

from bot.constants import USERS_PER_PAGE
from bot.services.report_service import ReportService
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.types.bots import EventBot

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def display_paginated_list(
    target: CallbackQuery | Message,
    bot: Bot,
    translator: NullTranslations,
    items_on_page: list[Any],
    total_items: int,
    page: int,
    title_text: str,
    empty_list_text: str,
    keyboard_factory: Callable[..., Awaitable[InlineKeyboardMarkup]],
    keyboard_factory_kwargs: dict[str, Any],
    page_size: int = USERS_PER_PAGE,
    server_host_for_display: str | None = None,
) -> None:
    """Displays or updates a paginated list in a Telegram message.

    This version works with pre-paginated data.

    Args:
        target: The Aiogram CallbackQuery (to edit message) or Message (to send
            new message / get chat_id).
        bot: The Aiogram Bot instance.
        translator: The gettext NullTranslations object for localization.
        items_on_page: The pre-sliced list of items for the current page.
        total_items: The total number of items across all pages.
        page: The current page number (0-indexed).
        title_text: The main title text for the message.
        empty_list_text: Text to display if there are no items at all.
        keyboard_factory: An async callable that returns an InlineKeyboardMarkup.
        keyboard_factory_kwargs: Additional keyword arguments for the keyboard_factory.
        page_size: Number of items per page.
        server_host_for_display: Optional server host string to append to the title.
    """
    _ = translator.gettext
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    current_page_idx = max(0, min(page, total_pages - 1))

    message_parts = [title_text]
    if total_items == 0:
        message_parts.append(empty_list_text)

    page_indicator_text = _("Page {current_page}/{total_pages}").format(
        current_page=current_page_idx + 1, total_pages=total_pages
    )

    if (
        server_host_for_display and " on {server_host}" not in message_parts[0]
    ):  # SIM102 fix applied here
        message_parts[0] += _(" on {server_host}").format(
            server_host=server_host_for_display
        )

    message_parts.append(f"\n{page_indicator_text}")
    final_message_text = "\n".join(message_parts)

    keyboard_markup = await keyboard_factory(
        translator,
        page_items=items_on_page,
        current_page=current_page_idx,
        total_pages=total_pages,
        **keyboard_factory_kwargs,
    )

    if isinstance(target, CallbackQuery) and isinstance(target.message, Message):
        await safe_edit_text(
            message_to_edit=target.message,
            text=final_message_text,
            reply_markup=keyboard_markup,
            parse_mode="HTML",
        )

    elif isinstance(target, Message):
        try:
            await bot.send_message(
                chat_id=target.chat.id,
                text=final_message_text,
                reply_markup=keyboard_markup,
                parse_mode="HTML",
            )
        except TelegramAPIError:
            logger.exception(
                "TelegramAPIError sending new paginated list for '%s' to chat %s",
                title_text,
                target.chat.id,
            )
    else:
        logger.error(
            "Invalid target type or unexpected state for display_paginated_list "
            "for '%s'. Target type: %s",
            title_text,
            type(target).__name__,
        )
        if isinstance(target, CallbackQuery):
            try:
                await target.answer(_("Error displaying list."), show_alert=True)
            except TelegramAPIError:
                logger.exception(
                    "Failed to answer callback for invalid target type for %s",
                    title_text,
                )


async def _show_subscriber_list_page(
    target: Message | CallbackQuery,
    report_service: ReportService,
    bot: EventBot,
    translator: NullTranslations,
    page: int = 0,
) -> None:
    """Fetches a paginated list of subscribers from the service and displays it."""
    _ = translator.gettext

    result = await report_service.get_subscribers_info(page=page)

    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},
        page_size=USERS_PER_PAGE,
    )


async def _show_banned_list_page(
    target: CallbackQuery | Message,
    report_service: ReportService,
    bot: EventBot,
    translator: NullTranslations,
    page: int,
) -> None:
    """Shows a paginated list of banned users."""
    _ = translator.gettext

    result = await report_service.get_banned_users_info(page=page)

    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
        page_size=USERS_PER_PAGE,
    )


async def safe_edit_text(
    message_to_edit: Message | InaccessibleMessage,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    *,
    disable_web_page_preview: bool | None = None,
) -> bool:
    """Safely edits a message text, handling common Telegram API errors."""
    if not isinstance(message_to_edit, Message):
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
            logger.warning(
                "TelegramBadRequest editing message for chat_id %s: %s",
                message_to_edit.chat.id,
                e,
            )
            return False
        # Message not modified is not a failure condition
        return True
    except TelegramAPIError:
        logger.warning(
            "TelegramAPIError editing message for chat_id %s", message_to_edit.chat.id
        )
        return False
    else:
        return True
