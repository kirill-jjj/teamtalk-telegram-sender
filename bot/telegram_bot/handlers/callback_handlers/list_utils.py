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
from bot.models import SubscribedUser
from bot.telegram_bot.api import get_display_names_for_ids
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list

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
    """Fetches a paginated list of subscribers from the DB and displays it."""
    _ = translator.gettext
    page_size = SUBSCRIBERS_PER_PAGE
    offset = page * page_size

    # 1. Get total count for pagination controls
    total_items = await subscriber_repo.count_all()

    # 2. Get only the IDs for the current page, sorted by telegram_id
    paginated_subscribers = await subscriber_repo.get_paginated(
        offset, page_size, order_by=SubscribedUser.telegram_id  # type: ignore[arg-type]
    )
    paginated_ids = [sub.telegram_id for sub in paginated_subscribers]

    # 3. Fetch user settings for just this page of subscribers
    user_settings_list = await user_repo.get_by_ids(paginated_ids)

    # 4. Get display names for just this page of users
    display_names = await get_display_names_for_ids(bot, paginated_ids)

    # 5. Create info objects for display
    user_infos = [
        SubscriberInfo(
            telegram_id=us.telegram_id,
            display_name=display_names.get(us.telegram_id, str(us.telegram_id)),
            teamtalk_username=us.teamtalk_username,
        )
        for us in user_settings_list
    ]
    # 6. Sort only the small list for the current page
    user_infos.sort(key=lambda user: user.display_name.lower())

    # 7. Display the paginated list using the updated utility
    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items_on_page=user_infos,
        total_items=total_items,
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
    page_size = SUBSCRIBERS_PER_PAGE
    offset = page * page_size

    total_items = await ban_repo.count_with_telegram_id()
    banned_entries = await ban_repo.get_paginated_with_telegram_id(offset, page_size)

    paginated_ids = [b.telegram_id for b in banned_entries if b.telegram_id]
    display_names = await get_display_names_for_ids(bot, paginated_ids)

    user_infos = [
        SubscriberInfo(
            telegram_id=b.telegram_id,
            display_name=display_names.get(b.telegram_id, str(b.telegram_id)),
            teamtalk_username=b.teamtalk_username,
        )
        for b in banned_entries
        if b.telegram_id is not None
    ]
    user_infos.sort(key=lambda user: user.display_name.lower())

    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items_on_page=user_infos,
        total_items=total_items,
        page=page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
        page_size=SUBSCRIBERS_PER_PAGE,
    )
