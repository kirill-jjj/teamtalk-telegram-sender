# This module contains utility functions for list display,
# pagination, and keyboard creation, moved here to avoid circular dependencies.

import logging
import asyncio
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_all_subscribers_ids
from bot.telegram_bot.models import SubscriberInfo
from bot.models import UserSettings # For UserSettings model

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10

async def _get_paginated_subscribers_info(
    session: AsyncSession,
    bot: Bot,
    requested_page: int
) -> tuple[list[SubscriberInfo], int, int]:
    """
    Fetches all subscriber IDs, gets their details, and returns a paginated list.
    Returns: (page_subscriber_info_list, current_page, total_pages)
    """
    all_subscriber_ids = await get_all_subscribers_ids(session)
    if not all_subscriber_ids:
        return [], 0, 0

    total_pages = (len(all_subscriber_ids) + SUBSCRIBERS_PER_PAGE - 1) // SUBSCRIBERS_PER_PAGE

    current_page_num = requested_page
    if current_page_num < 0:
        current_page_num = 0

    # Adjust if requested_page is too high
    if current_page_num >= total_pages and total_pages > 0:
        current_page_num = total_pages - 1
    elif total_pages == 0: # No pages, so page 0
        current_page_num = 0
        return [], 0, 0 # No subscribers, no pages

    # Initial slice for page_ids
    start_idx = current_page_num * SUBSCRIBERS_PER_PAGE
    end_idx = start_idx + SUBSCRIBERS_PER_PAGE
    page_ids_to_fetch = all_subscriber_ids[start_idx:end_idx]

    # If current page is empty (e.g. after deletions) and it's not page 0, try previous page
    if not page_ids_to_fetch and current_page_num > 0:
        current_page_num -= 1
        start_idx = current_page_num * SUBSCRIBERS_PER_PAGE
        end_idx = start_idx + SUBSCRIBERS_PER_PAGE
        page_ids_to_fetch = all_subscriber_ids[start_idx:end_idx]

    if not page_ids_to_fetch: # If still no IDs for any valid page
        return [], current_page_num, total_pages

    # Fetch chat info concurrently for the current page's IDs
    chat_info_tasks = [bot.get_chat(tg_id) for tg_id in page_ids_to_fetch]

    # Fetch UserSettings concurrently for the current page's IDs
    user_settings_tasks = [session.get(UserSettings, tg_id) for tg_id in page_ids_to_fetch]

    chat_results = await asyncio.gather(*chat_info_tasks, return_exceptions=True)
    user_settings_results = await asyncio.gather(*user_settings_tasks, return_exceptions=True)

    page_subscribers_info = []
    for i, telegram_id in enumerate(page_ids_to_fetch):
        display_name = str(telegram_id)
        chat_result = chat_results[i]
        if isinstance(chat_result, Exception):
            logger.error(f"Could not fetch chat info for Telegram ID {telegram_id}: {chat_result}")
        else:
            chat_info = chat_result
            full_name = f"{chat_info.first_name or ''} {chat_info.last_name or ''}".strip()
            username_part = f" (@{chat_info.username})" if chat_info.username else ""
            if full_name:
                display_name = f"{full_name}{username_part}"
            elif chat_info.username:
                display_name = f"@{chat_info.username}"

        tt_username: str | None = None
        user_setting_result = user_settings_results[i]
        if isinstance(user_setting_result, Exception):
            logger.error(f"Could not fetch user settings for Telegram ID {telegram_id}: {user_setting_result}")
        elif user_setting_result:
            tt_username = user_setting_result.teamtalk_username

        page_subscribers_info.append(SubscriberInfo(
            telegram_id=telegram_id,
            display_name=display_name,
            teamtalk_username=tt_username
        ))

    return page_subscribers_info, current_page_num, total_pages


async def _show_subscriber_list_page(
    target: "Message | CallbackQuery", # Use quotes for forward reference if Message/CallbackQuery not imported
    session: AsyncSession,
    bot: Bot,
    _: callable,
    page: int = 0
):
    """Fetches and displays a specific page of the subscriber list."""
    from aiogram.types import Message, CallbackQuery # Local import for type hint
    from bot.telegram_bot.utils import send_or_edit_paginated_list # Local import
    from bot.telegram_bot.keyboards import create_subscriber_list_keyboard # Local import

    page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
        session, bot, requested_page=page
    )

    if total_pages == 0 or not page_subscribers_info:
        await send_or_edit_paginated_list(
            target=target,
            text=_("No subscribers found."),
            bot=bot
        )
        return

    keyboard = create_subscriber_list_keyboard(
        _,
        page_subscribers_info=page_subscribers_info,
        current_page=current_page,
        total_pages=total_pages
    )

    await send_or_edit_paginated_list(
        target=target,
        text=_("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
            current_page_display=current_page + 1,
            total_pages=total_pages
        ),
        reply_markup=keyboard,
        bot=bot
    )
