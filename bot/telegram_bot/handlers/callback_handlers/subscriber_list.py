import logging
from aiogram import Router, Bot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.exceptions import TelegramAPIError

from bot.database.crud import delete_user_data_fully, get_all_subscribers_ids
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.filters import IsAdminFilter

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10

subscriber_list_router = Router(name="subscriber_list_actions_router")
subscriber_list_router.callback_query.filter(IsAdminFilter())

async def _get_paginated_subscribers_info(
    session: AsyncSession,
    bot: Bot,
    requested_page: int
) -> tuple[list[dict], int, int]:
    """
    Fetches all subscriber IDs, gets their details, and returns a paginated list.
    Returns: (page_subscriber_info_list, current_page, total_pages)
    """
    all_subscriber_ids = await get_all_subscribers_ids(session)
    if not all_subscriber_ids:
        return [], 0, 0

    all_subscribers_info = []
    for telegram_id in all_subscriber_ids:
        display_name = str(telegram_id)  # Default display name
        try:
            chat_info = await bot.get_chat(telegram_id)
            full_name = f"{chat_info.first_name or ''} {chat_info.last_name or ''}".strip()
            username_part = f" (@{chat_info.username})" if chat_info.username else ""

            if full_name:
                display_name = f"{full_name}{username_part}"
            elif chat_info.username:
                display_name = f"@{chat_info.username}"
        except TelegramAPIError as e:
            logger.error(f"Could not fetch chat info for Telegram ID {telegram_id} in callback: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching chat info for Telegram ID {telegram_id} in callback: {e}")

        all_subscribers_info.append({'telegram_id': telegram_id, 'display_name': display_name})

    if not all_subscribers_info: # Should technically be caught by all_subscriber_ids check
        return [], 0, 0

    total_pages = (len(all_subscribers_info) + SUBSCRIBERS_PER_PAGE - 1) // SUBSCRIBERS_PER_PAGE

    current_page = requested_page
    if current_page < 0:
        current_page = 0
    if current_page >= total_pages and total_pages > 0:
        current_page = total_pages - 1

    if total_pages == 0: # No subscribers left after potential filtering/errors
        return [], 0, 0

    start_index = current_page * SUBSCRIBERS_PER_PAGE
    end_index = start_index + SUBSCRIBERS_PER_PAGE
    page_data_slice = all_subscribers_info[start_index:end_index]

    # If the current page is now empty due to deletions and it's not page 0, try to go to the previous page.
    if not page_data_slice and current_page > 0:
        current_page -= 1
        start_index = current_page * SUBSCRIBERS_PER_PAGE
        end_index = start_index + SUBSCRIBERS_PER_PAGE
        page_data_slice = all_subscribers_info[start_index:end_index]

    return page_data_slice, current_page, total_pages


@subscriber_list_router.callback_query(SubscriberListCallback.filter())
async def handle_subscriber_list_actions(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    session: AsyncSession,
    bot: Bot, # Added Bot
    _: callable
):
    """Handles actions from the subscriber list keyboard (delete, paginate)."""
    action = callback_data.action
    page_from_callback = callback_data.page if callback_data.page is not None else 0

    if action == "delete_subscriber":
        if callback_data.telegram_id is None:
            await query.answer(_("Error: No Telegram ID specified for deletion."), show_alert=True)
            return

        telegram_id_to_delete = callback_data.telegram_id
        success = await delete_user_data_fully(session, telegram_id_to_delete)

        if success:
            await query.answer(_("Subscriber {telegram_id} deleted successfully.").format(telegram_id=telegram_id_to_delete)) # SUBSCRIBER_DELETED_SUCCESS
        else:
            await query.answer(_("Error deleting subscriber {telegram_id}.").format(telegram_id=telegram_id_to_delete), show_alert=True) # SUBSCRIBER_DELETE_ERROR

        # Refresh the list using the helper
        page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
            session, bot, page_from_callback
        )

        if total_pages == 0 or not page_subscribers_info:
            await query.message.edit_text(_("No subscribers found.")) # SUBSCRIBERS_NONE_FOUND
        else:
            new_keyboard = create_subscriber_list_keyboard(
                _,
                subscribers_info=page_subscribers_info,
                current_page=current_page,
                total_pages=total_pages
            )
            await query.message.edit_text(
                _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                    current_page_display=current_page + 1,
                    total_pages=total_pages
                ), # SUBSCRIBERS_LIST_HEADER
                reply_markup=new_keyboard
            )

    elif action == "page":
        requested_page = callback_data.page
        if requested_page is None:
            await query.answer("Error: Page number missing.", show_alert=True)
            return

        page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
            session, bot, requested_page
        )

        if total_pages == 0 or not page_subscribers_info:
            await query.message.edit_text(_("No subscribers found.")) # SUBSCRIBERS_NONE_FOUND
        else:
            keyboard = create_subscriber_list_keyboard(
                _,
                subscribers_info=page_subscribers_info,
                current_page=current_page,
                total_pages=total_pages
            )
            await query.message.edit_text(
                _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                    current_page_display=current_page + 1,
                    total_pages=total_pages
                ), # SUBSCRIBERS_LIST_HEADER
                reply_markup=keyboard
            )
        await query.answer()
    else:
        await query.answer(_("Unknown action."), show_alert=True) # UNKNOWN_ACTION
