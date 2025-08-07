"""Utility functions for displaying paginated lists in Telegram messages."""

from __future__ import annotations

from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, Message

from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list
from bot.telegram_bot.utils import get_display_names_for_ids

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10


async def _show_subscriber_list_page(
    target: Message | CallbackQuery,
    user_repo: UserRepository,
    subscriber_repo: SubscriberRepository,
    bot: EventBot,
    translator: NullTranslations,
    page: int = 0,
) -> None:
    """Fetches all subscribers and displays a paginated list."""
    _ = translator.gettext
    all_subscriber_ids = await subscriber_repo.get_all_ids()
    user_settings_list = await user_repo.get_by_ids(all_subscriber_ids)

    display_names = await get_display_names_for_ids(bot, [us.telegram_id for us in user_settings_list])

    user_infos = [
        SubscriberInfo(
            telegram_id=us.telegram_id,
            display_name=display_names.get(us.telegram_id, str(us.telegram_id)),
            teamtalk_username=us.teamtalk_username,
        )
        for us in user_settings_list
    ]
    user_infos.sort(key=lambda user: user.display_name.lower())

    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items=user_infos,
        page=page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},
        page_size=SUBSCRIBERS_PER_PAGE,
    )


async def _show_banned_list_page(
    target: CallbackQuery | Message,
    ban_repo: BanRepository,
    bot: EventBot,
    translator: NullTranslations,
    page: int,
) -> None:
    """Shows a paginated list of banned users."""
    _ = translator.gettext
    banned_entries = await ban_repo.get_all()
    # Filter for entries that have a telegram_id, as we can't display users without it
    banned_with_tg_id = [b for b in banned_entries if b.telegram_id is not None]

    display_names = await get_display_names_for_ids(bot, [b.telegram_id for b in banned_with_tg_id if b.telegram_id])

    user_infos = [
        SubscriberInfo(
            telegram_id=b.telegram_id,
            display_name=display_names.get(b.telegram_id, str(b.telegram_id)),
            teamtalk_username=b.teamtalk_username,
        )
        for b in banned_with_tg_id
        if b.telegram_id is not None
    ]
    user_infos.sort(key=lambda user: user.display_name.lower())

    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items=user_infos,
        page=page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
        page_size=SUBSCRIBERS_PER_PAGE,
    )
