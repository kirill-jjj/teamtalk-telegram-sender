import logging
import asyncio
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_all_subscribers_ids
from bot.services import user_service
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.utils import send_or_edit_paginated_list # Added import
from bot.core.enums import SubscriberListAction
from bot.state import ADMIN_IDS_CACHE

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10

subscriber_list_router = Router(name="subscriber_list_actions_router")

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
    # Assuming USER_SETTINGS_CACHE is up-to-date or get_or_create_user_settings can be used.
    # For simplicity here, let's fetch them. If performance is an issue, caching or a more complex query is needed.
    # We need the UserSettings model for this.
    from bot.models import UserSettings # Import UserSettings
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


@subscriber_list_router.callback_query(SubscriberListCallback.filter(), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def handle_subscriber_list_actions(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    session: AsyncSession,
    bot: Bot,
    _: callable
):
    """Handles actions from the subscriber list keyboard (delete, paginate)."""
    action = callback_data.action
    page_from_callback = callback_data.page if callback_data.page is not None else 0

    if action == SubscriberListAction.DELETE_SUBSCRIBER:
        if callback_data.telegram_id is None:
            await query.answer(_("Error: No Telegram ID specified for deletion."), show_alert=True)
            return

        telegram_id_to_delete = callback_data.telegram_id
        success = await user_service.delete_full_user_profile(session, telegram_id_to_delete)

        if success:
            await query.answer(_("Subscriber {telegram_id} deleted successfully.").format(telegram_id=telegram_id_to_delete))
        else:
            await query.answer(_("Error deleting subscriber {telegram_id}.").format(telegram_id=telegram_id_to_delete), show_alert=True)

        page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
            session, bot, page_from_callback
        )

        if total_pages == 0 or not page_subscribers_info:
            await send_or_edit_paginated_list(
                target=query,
                text=_("No subscribers found.")
            )
        else:
            new_keyboard = create_subscriber_list_keyboard(
                _,
                page_subscribers_info=page_subscribers_info,
                current_page=current_page,
                total_pages=total_pages
            )
            await send_or_edit_paginated_list(
                target=query,
                text=_("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                    current_page_display=current_page + 1,
                    total_pages=total_pages
                ),
                reply_markup=new_keyboard
            )
        # query.answer() is handled by send_or_edit_paginated_list for non-alert answers

    elif action == SubscriberListAction.PAGE:
        requested_page = callback_data.page
        if requested_page is None:
            await query.answer(_("Error: Page number missing."), show_alert=True)
            return

        page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
            session, bot, requested_page
        )

        if total_pages == 0 or not page_subscribers_info:
            await send_or_edit_paginated_list(
                target=query,
                text=_("No subscribers found.")
            )
        else:
            keyboard = create_subscriber_list_keyboard(
                _,
                page_subscribers_info=page_subscribers_info,
                current_page=current_page,
                total_pages=total_pages
            )
            await send_or_edit_paginated_list(
                target=query,
                text=_("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                    current_page_display=current_page + 1,
                    total_pages=total_pages
                ),
                reply_markup=keyboard
            )
        # query.answer() is handled by send_or_edit_paginated_list for non-alert answers
    else:
        # This case should ideally not be reached if action is always a valid enum member.
        # Logging defensively.
        logger.warning(f"Unhandled SubscriberListAction: {action} from user {query.from_user.id}")
        await query.answer(_("Unknown action."), show_alert=True)
