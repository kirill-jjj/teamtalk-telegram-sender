"""Utility functions for displaying paginated lists in Telegram messages."""
# This module contains utility functions for list display,
# pagination, and keyboard creation, moved here to avoid circular dependencies.

from __future__ import annotations

from collections.abc import Callable
import gettext
import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.types import CallbackQuery
from sqlalchemy.sql.selectable import Select
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


async def _prepare_user_list(
    session: AsyncSession,
    bot: Bot,
    statement: Select[Any],
    extractor: Callable[[Any], tuple[int, str | None] | None],
) -> list[SubscriberInfo]:
    """A generic helper to fetch entities from the DB, get their display names, and sort them.

    :param session: The database session.
    :param bot: The bot instance for fetching user names.
    :param statement: The SQLAlchemy select statement to execute.
    :param extractor: A function that takes a DB entity and returns a tuple of
                      (telegram_id, teamtalk_username) or None.
    :return: A sorted list of SubscriberInfo objects.
    """
    db_results = (await session.exec(statement)).all()  # type: ignore[call-overload]
    if not db_results:
        return []

    extracted_data = [extractor(item) for item in db_results]
    valid_data = [data for data in extracted_data if data is not None]

    telegram_ids = [data[0] for data in valid_data]
    display_names = await get_display_names_for_ids(bot, telegram_ids)

    user_info_list = [
        SubscriberInfo(
            telegram_id=data[0],
            display_name=display_names.get(data[0], str(data[0])),
            teamtalk_username=data[1],
        )
        for data in valid_data
    ]

    user_info_list.sort(key=lambda user: user.display_name.lower())
    return user_info_list


async def _get_all_subscribers_info(session: AsyncSession, bot: Bot) -> list[SubscriberInfo]:
    """Fetches all subscriber details using the generic _prepare_user_list helper."""
    all_subscriber_ids = await get_all_subscribers_ids(session)
    if not all_subscriber_ids:
        return []

    statement = select(UserSettings).where(UserSettings.telegram_id.in_(all_subscriber_ids))  # type: ignore[attr-defined]

    def extractor(user_settings: UserSettings) -> tuple[int, str | None]:
        return user_settings.telegram_id, user_settings.teamtalk_username

    return await _prepare_user_list(session, bot, statement, extractor)


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
