"""Utility functions for displaying paginated lists in Telegram messages."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
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


T = TypeVar("T")


class UserInfo(Protocol):
    """Protocol for objects containing user information."""

    telegram_id: int | None
    teamtalk_username: str | None


class UserListRepository(Protocol[T]):
    """Protocol for repositories that provide paginated lists of users."""

    def count_all(self) -> Coroutine[Any, Any, int]:
        """Counts all items in the repository."""
        ...

    def get_paginated(
        self, offset: int, limit: int
    ) -> Coroutine[Any, Any, list[T]]:
        """Retrieves a paginated list of items."""
        ...


async def _get_user_list_info(
    bot: EventBot,
    user_repo: UserRepository,
    source_repo: UserListRepository[UserInfo],
    page: int,
    page_size: int,
    repo_counter_method_name: str,
    repo_paginator_method_name: str,
) -> tuple[int, list[SubscriberInfo]]:
    """Fetches, processes, and sorts a paginated list of user information.

    This helper encapsulates the common logic of fetching a page of users from a
    repository, getting their display names, creating `SubscriberInfo` objects,
    and sorting them.
    """
    offset = page * page_size

    counter_method = getattr(source_repo, repo_counter_method_name)
    paginator_method = getattr(source_repo, repo_paginator_method_name)

    total_items = await counter_method()
    paginated_items = await paginator_method(offset, page_size)

    paginated_ids = [item.telegram_id for item in paginated_items if item.telegram_id]

    user_settings_list = await user_repo.get_by_ids(paginated_ids)
    display_names = await get_display_names_for_ids(bot, paginated_ids)

    user_settings_map = {us.telegram_id: us for us in user_settings_list}

    user_infos = []
    for item in paginated_items:
        if item.telegram_id is None:
            continue
        user_settings = user_settings_map.get(item.telegram_id)
        teamtalk_username = (
            user_settings.teamtalk_username
            if user_settings
            else getattr(item, "teamtalk_username", None)
        )
        user_infos.append(
            SubscriberInfo(
                telegram_id=item.telegram_id,
                display_name=display_names.get(item.telegram_id, str(item.telegram_id)),
                teamtalk_username=teamtalk_username,
            )
        )

    user_infos.sort(key=lambda user: user.display_name.lower())
    return total_items, user_infos


async def _show_paginated_user_list(
    target: Message | CallbackQuery,
    bot: EventBot,
    translator: NullTranslations,
    user_repo: UserRepository,
    source_repo: UserListRepository[Any],
    page: int,
    title_text: str,
    empty_list_text: str,
    keyboard_factory: Callable[
        [NullTranslations, list[Any], int, int], Awaitable[InlineKeyboardMarkup]
    ],
    repo_counter_method_name: str,
    repo_paginator_method_name: str,
) -> None:
    """Generic function to display a paginated list of users."""
    total_items, user_infos = await _get_user_list_info(
        bot=bot,
        user_repo=user_repo,
        source_repo=source_repo,
        page=page,
        page_size=SUBSCRIBERS_PER_PAGE,
        repo_counter_method_name=repo_counter_method_name,
        repo_paginator_method_name=repo_paginator_method_name,
    )

    await display_paginated_list(
        target=target,
        bot=bot,
        translator=translator,
        items_on_page=user_infos,
        total_items=total_items,
        page=page,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=keyboard_factory,
        keyboard_factory_kwargs={},
        page_size=SUBSCRIBERS_PER_PAGE,
    )


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
    await _show_paginated_user_list(
        target=target,
        bot=bot,
        translator=translator,
        user_repo=user_repo,
        source_repo=subscriber_repo,
        page=page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        repo_counter_method_name="count_all",
        repo_paginator_method_name="get_paginated",
    )


async def _show_banned_list_page(
    target: CallbackQuery | Message,
    ban_repo: BanRepository,
    user_repo: UserRepository,
    bot: EventBot,
    translator: NullTranslations,
    page: int,
) -> None:
    """Shows a paginated list of banned users."""
    _ = translator.gettext
    await _show_paginated_user_list(
        target=target,
        bot=bot,
        translator=translator,
        user_repo=user_repo,
        source_repo=ban_repo,
        page=page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        repo_counter_method_name="count_with_telegram_id",
        repo_paginator_method_name="get_paginated_with_telegram_id",
    )
