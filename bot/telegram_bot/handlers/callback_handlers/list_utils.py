"""Utility functions for displaying paginated lists in Telegram messages."""
# This module contains utility functions for list display,
# pagination, and keyboard creation, moved here to avoid circular dependencies.

from __future__ import annotations

from collections.abc import Awaitable, Callable
import gettext
import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.sql.selectable import Select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, Message

from bot.database.crud import get_all_subscribers_ids
from bot.models import BanList, UserSettings
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
)
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


async def _show_generic_user_list(
    target: Message | CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    translator: gettext.GNUTranslations,
    page: int,
    statement: Select[Any],
    extractor: Callable[[Any], tuple[int, str | None] | None],
    title_text_key: str,
    empty_list_text_key: str,
    keyboard_factory: Callable[..., Awaitable[InlineKeyboardMarkup]],
) -> None:
    """A generic function to display a paginated list of users."""
    _ = translator.gettext
    user_infos = await _prepare_user_list(session, bot, statement, extractor)
    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items=user_infos,
        page=page,
        title_text=_(title_text_key),
        empty_list_text=_(empty_list_text_key),
        keyboard_factory=keyboard_factory,
        keyboard_factory_kwargs={},
        page_size=SUBSCRIBERS_PER_PAGE,
    )


async def _show_subscriber_list_page(
    target: Message | CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    translator: gettext.GNUTranslations,
    page: int = 0,
) -> None:
    """Fetches all subscribers and displays a paginated list."""
    all_subscriber_ids = await get_all_subscribers_ids(session)
    statement = select(UserSettings).where(
        UserSettings.telegram_id.in_(all_subscriber_ids)  # type: ignore[attr-defined]
    )

    def extractor(user_settings: UserSettings) -> tuple[int, str | None]:
        return user_settings.telegram_id, user_settings.teamtalk_username

    await _show_generic_user_list(
        target=target,
        session=session,
        bot=bot,
        translator=translator,
        page=page,
        statement=statement,
        extractor=extractor,
        title_text_key=_("Here is the list of subscribers."),
        empty_list_text_key="No subscribers found.",
        keyboard_factory=create_subscriber_list_keyboard,
    )


async def _show_banned_list_page(
    target: CallbackQuery | Message,
    session: AsyncSession,
    bot: Bot,
    translator: gettext.GNUTranslations,
    page: int,
) -> None:
    """Shows a paginated list of banned users."""
    statement = select(BanList).where(BanList.telegram_id.isnot(None))  # type: ignore[union-attr]

    def extractor(ban_entry: BanList) -> tuple[int, str | None] | None:
        # This check is technically redundant due to the WHERE clause,
        # but it's good practice for robustness.
        if ban_entry.telegram_id is None:
            logger.error("BanList entry with id %s has null telegram_id.", ban_entry.id)
            return None
        return ban_entry.telegram_id, ban_entry.teamtalk_username

    await _show_generic_user_list(
        target=target,
        session=session,
        bot=bot,
        translator=translator,
        page=page,
        statement=statement,
        extractor=extractor,
        title_text_key="Banned Users",
        empty_list_text_key="The ban list is empty.",
        keyboard_factory=create_banned_user_list_keyboard,
    )
