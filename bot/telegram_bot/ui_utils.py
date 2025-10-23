"""Utility functions for creating and managing UI elements like paginated lists."""

from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Any, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
)

from bot.constants import MSG_GENERAL_ERROR, USERS_PER_PAGE
from bot.telegram_bot.formatters import (
    format_moderation_prompt,
    format_paginated_list_text,
)
from bot.telegram_bot.keyboards import (
    create_toggle_mute_keyboard,
    create_user_selection_keyboard,
)
from bot.utils.pagination import paginate_list

if TYPE_CHECKING:
    from bot.core.enums import AdminCommand
    from bot.services.schemas import ModerationViewData

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def _display_user_list(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    page: int,
    items: list[Any],
    sort_key_extractor: Callable[[Any], Any],
    title_text: str,
    empty_list_text: str,
    keyboard_factory_kwargs: dict[str, Any],
    server_host_for_display: str | None = None,
) -> None:
    """A generic helper to display a paginated list of users."""
    _ = translator.gettext
    sorted_items = sorted(items, key=sort_key_extractor)

    if callback_query.bot is None:
        logger.error("Cannot display user list: bot is None.")
        await callback_query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
        return

    page_slice, _total_pages, current_page_idx = paginate_list(
        sorted_items, page, USERS_PER_PAGE
    )

    await display_paginated_list(
        target=callback_query,
        bot=callback_query.bot,
        translator=translator,
        items_on_page=page_slice,
        total_items=len(sorted_items),
        page=current_page_idx,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_toggle_mute_keyboard,
        keyboard_factory_kwargs=keyboard_factory_kwargs,
        page_size=USERS_PER_PAGE,
        server_host_for_display=server_host_for_display,
    )


async def display_moderation_view(
    message: Message,
    translator: NullTranslations,
    command_type: "AdminCommand",
    view_data: "ModerationViewData",
) -> None:
    """Displays the moderation view: a list of users or an error message."""
    _ = translator.gettext

    if not view_data.users:
        await message.reply(view_data.error_message or _("Failed to get user list."))
        return

    builder = create_user_selection_keyboard(view_data.users, command_type)
    reply_text = format_moderation_prompt(
        command_type, view_data.server_name, translator
    )

    await message.reply(reply_text, reply_markup=builder.as_markup())


async def display_paginated_list(
    target: CallbackQuery | Message,
    bot: Bot,
    translator: NullTranslations,
    items_on_page: list[Any],
    total_items: int,
    page: int,
    title_text: str,
    empty_list_text: str,
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
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

    final_message_text = format_paginated_list_text(
        translator=translator,
        title_text=title_text,
        total_items=total_items,
        page=page,
        page_size=page_size,
        empty_list_text=empty_list_text,
        server_host_for_display=server_host_for_display,
    )

    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    current_page_idx = max(0, min(page, total_pages - 1))

    keyboard_markup = keyboard_factory(
        translator,
        page_items=items_on_page,
        current_page=current_page_idx,
        total_pages=total_pages,
        **keyboard_factory_kwargs,
    )

    if isinstance(target, CallbackQuery) and isinstance(target.message, Message):
        await edit_message_text(
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


async def edit_message_text(
    message_to_edit: Message | InaccessibleMessage,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    *,
    disable_web_page_preview: bool | None = None,
) -> bool:
    """Edits a message text, handling common Telegram API errors."""
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
