"""Utility functions for displaying paginated lists in Telegram messages."""
# This module contains utility functions for list display,
# pagination, and keyboard creation, moved here to avoid circular dependencies.

from __future__ import annotations

import asyncio
import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, Chat
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, Message

from bot.database.crud import get_all_subscribers_ids
from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.ui_utils import display_paginated_list
from bot.telegram_bot.utils import format_telegram_user_display_name

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10


async def _get_all_subscribers_info(session: AsyncSession, bot: Bot) -> list[SubscriberInfo]:
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

    # The isinstance(target, CallbackQuery) check is removed,
    # as display_paginated_list now handles both Message and CallbackQuery targets.

    all_subscribers_info = await _get_all_subscribers_info(session, bot)

    # The `bot` object passed to this function will be relayed to display_paginated_list.
    # if `callback_query.bot` is used internally by `safe_edit_text`.
    # However, `create_subscriber_list_keyboard` might need it or other specific args.
    await display_paginated_list(
        target=target,  # Pass target
        bot=bot,  # Pass bot instance
        translator=translator,
        items=all_subscribers_info,
        page=page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},  # Add any specific kwargs needed by create_subscriber_list_keyboard
        page_size=SUBSCRIBERS_PER_PAGE,
    )
