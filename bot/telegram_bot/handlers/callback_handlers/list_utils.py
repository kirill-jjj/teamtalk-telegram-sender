"""Utility functions for displaying paginated lists in Telegram messages."""
# This module contains utility functions for list display,
# pagination, and keyboard creation, moved here to avoid circular dependencies.

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, Message

from bot.database.crud import get_all_subscribers_ids
from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.ui_utils import display_paginated_list
from bot.telegram_bot.utils import get_display_names_for_ids

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10


async def _get_all_subscribers_info(session: AsyncSession, bot: Bot) -> list[SubscriberInfo]:
    """Fetches subscriber details using the centralized get_display_names_for_ids."""
    all_subscriber_ids = await get_all_subscribers_ids(session)
    if not all_subscriber_ids:
        return []

    user_settings_list = (
        await session.exec(select(UserSettings).where(UserSettings.telegram_id.in_(all_subscriber_ids)))  # type: ignore[attr-defined]
    ).all()
    user_settings_map = {us.telegram_id: us for us in user_settings_list}

    display_names = await get_display_names_for_ids(bot, all_subscriber_ids)

    all_subscribers_info = [
        SubscriberInfo(
            telegram_id=telegram_id,
            display_name=display_names.get(telegram_id, str(telegram_id)),
            teamtalk_username=(
                user_settings_map[telegram_id].teamtalk_username if telegram_id in user_settings_map else None
            ),
        )
        for telegram_id in all_subscriber_ids
    ]

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
