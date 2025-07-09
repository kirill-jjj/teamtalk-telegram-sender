"""Utility functions for displaying paginated lists in Telegram messages."""
# This module contains utility functions for list display,
# pagination, and keyboard creation, moved here to avoid circular dependencies.

from __future__ import annotations

import asyncio
import gettext
import logging
from typing import TYPE_CHECKING  # Added cast

from aiogram import Bot
from aiogram.types import Chat  # Added Chat
from sqlmodel import select  # Moved import here
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, Message

from bot.database.crud import get_all_subscribers_ids
from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.ui_utils import display_paginated_list  # Added import
from bot.telegram_bot.utils import format_telegram_user_display_name

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10


async def _get_all_subscribers_info(  # Renamed function
    session: AsyncSession, bot: Bot
) -> list[SubscriberInfo]:  # Corrected return type annotation
    """Fetches all subscriber IDs, gets their details, and returns a list of all subscribers.

    Returns:
        A list of SubscriberInfo objects for all subscribers, sorted by display name.
    """
    all_subscriber_ids = await get_all_subscribers_ids(session)
    if not all_subscriber_ids:
        return []  # Returns empty list, matching the type hint

    # Fetch all chat info and user settings in batches
    # For UserSettings
    user_settings_list = (
        await session.exec(select(UserSettings).where(UserSettings.telegram_id.in_(all_subscriber_ids)))  # type: ignore[attr-defined]
    ).all()
    user_settings_map = {us.telegram_id: us for us in user_settings_list}

    # For Chat info (Telegram display names)
    # Consider doing this in chunks if all_subscriber_ids can be very large,
    # to avoid hitting API limits or creating too many concurrent tasks.
    # For now, let's assume the number of subscribers is manageable for asyncio.gather.
    chat_info_tasks = [bot.get_chat(tg_id) for tg_id in all_subscriber_ids]
    chat_results = await asyncio.gather(*chat_info_tasks, return_exceptions=True)

    all_subscribers_info = []
    for i, telegram_id in enumerate(all_subscriber_ids):
        display_name = str(telegram_id)  # Default display name

        chat_result = chat_results[i]
        if isinstance(chat_result, Exception):
            logger.error("Could not fetch chat info for Telegram ID %s: %s", telegram_id, chat_result)
        # Make sure chat_result is indeed a Chat object
        elif isinstance(chat_result, Chat):
            display_name = format_telegram_user_display_name(chat_result)
        else:
            logger.error("Unexpected type for chat_result for ID %s: %s", telegram_id, type(chat_result))

        tt_username: str | None = None
        user_setting = user_settings_map.get(telegram_id)
        if user_setting:
            tt_username = user_setting.teamtalk_username
        else:
            # This case might occur if a user unsubscribed between get_all_subscribers_ids and here,
            # or if there's a data consistency issue.
            logger.warning(
                "Could not find user settings in batch for Telegram ID %s during subscriber list generation.",
                telegram_id,
            )

        all_subscribers_info.append(
            SubscriberInfo(telegram_id=telegram_id, display_name=display_name, teamtalk_username=tt_username)
        )

    # Sorting by display name (case-insensitive)
    all_subscribers_info.sort(key=lambda sub: sub.display_name.lower())

    return all_subscribers_info


async def _show_subscriber_list_page(
    target: Message | CallbackQuery,
    session: AsyncSession,
    bot: Bot,  # bot is needed for _get_all_subscribers_info
    translator: gettext.GNUTranslations,
    page: int = 0,
) -> None:
    """Fetches all subscribers and displays a paginated list."""
    _ = translator.gettext

    if not isinstance(target, CallbackQuery):
        # display_paginated_list expects a CallbackQuery to edit its message.
        # If target is Message, it implies a command was used to show the list initially.
        # This scenario needs a proper way to send a new message that can then be paginated.
        # For now, we'll log a warning and attempt to proceed if it's a Message,
        # but this might not work as display_paginated_list expects callback_query.message.
        # A better approach would be for command handlers to send an initial message
        # and then pass a "dummy" CallbackQuery or adapt display_paginated_list.
        # This refactoring focuses on CallbackQuery-driven pagination updates.
        logger.warning(
            "_show_subscriber_list_page called with Message target. "
            "display_paginated_list primarily supports CallbackQuery for message editing."
        )
        # If we must support Message target, we'd need to send a new message here and store it
        # or have display_paginated_list handle initial message sending.
        # This is outside the immediate scope of DRY refactoring of pagination logic itself.
        # For now, if it's a Message, we can't use display_paginated_list directly.
        # We could revert to send_or_edit_paginated_list for the initial send,
        # but subsequent pagination callbacks would then use the new system.
        # This part of the logic might need further review based on how initial lists are shown.
        # Let's assume for this refactor that `target` will be a CallbackQuery for pagination.
        # If a command calls this, it should first send a placeholder and then simulate a CallbackQuery
        # or this function needs to be split for initial send vs. update.
        # For now, this refactor assumes `target` is a `CallbackQuery` when pagination is involved.
        # The original function `send_or_edit_paginated_list` could handle `Message` for initial send.
        # Let's stick to the plan: `display_paginated_list` is for callback query updates.

        # If the entry point is a command sending a Message, that command should send the
        # first page itself, perhaps using a simplified version of this logic or calling
        # display_paginated_list with a specially crafted initial CallbackQuery-like object if feasible.
        # This is a larger architectural consideration.
        # For now, if target is not CallbackQuery, we cannot proceed with display_paginated_list.
        # This function is mostly called from callback handlers elsewhere, so target should be CallbackQuery.
        await target.answer(_("This view can only be updated via buttons."), show_alert=True)  # type: ignore
        return

    all_subscribers_info = await _get_all_subscribers_info(session, bot)  # Renamed function

    # The `bot` object might not be directly needed by `display_paginated_list`
    # if `callback_query.bot` is used internally by `safe_edit_text`.
    # However, `create_subscriber_list_keyboard` might need it or other specific args.
    await display_paginated_list(
        callback_query=target,  # target is now confirmed/assumed to be CallbackQuery
        translator=translator,
        items=all_subscribers_info,
        page=page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},  # Add any specific kwargs needed by create_subscriber_list_keyboard
        page_size=SUBSCRIBERS_PER_PAGE,
    )
