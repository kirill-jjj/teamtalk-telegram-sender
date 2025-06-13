import logging
from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import delete_user_data_fully, get_all_subscribers_ids
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.filters import IsAdminFilter

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10

subscriber_list_router = Router(name="subscriber_list_actions_router")
subscriber_list_router.callback_query.filter(IsAdminFilter())

@subscriber_list_router.callback_query(SubscriberListCallback.filter())
async def handle_subscriber_list_actions(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    session: AsyncSession,
    _: callable
):
    """Handles actions from the subscriber list keyboard (delete, paginate)."""
    action = callback_data.action
    current_page_from_callback = callback_data.page if callback_data.page is not None else 0

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

        # Refresh the list
        all_subscriber_ids = await get_all_subscribers_ids(session)
        if not all_subscriber_ids:
            await query.message.edit_text(_("No subscribers found.")) # SUBSCRIBERS_NONE_FOUND
            return

        total_pages = (len(all_subscriber_ids) + SUBSCRIBERS_PER_PAGE - 1) // SUBSCRIBERS_PER_PAGE
        current_page = current_page_from_callback

        if current_page >= total_pages and total_pages > 0:
            current_page = total_pages - 1
        elif total_pages == 0: # Should be caught by earlier check, but defensive
             await query.message.edit_text(_("No subscribers found."))
             return


        start_index = current_page * SUBSCRIBERS_PER_PAGE
        end_index = start_index + SUBSCRIBERS_PER_PAGE
        page_subscriber_ids = all_subscriber_ids[start_index:end_index]

        if not page_subscriber_ids and current_page > 0: # If current page became empty, try previous
            current_page -=1
            start_index = current_page * SUBSCRIBERS_PER_PAGE
            end_index = start_index + SUBSCRIBERS_PER_PAGE
            page_subscriber_ids = all_subscriber_ids[start_index:end_index]

        if not page_subscriber_ids and total_pages > 0: # Still no users on any page, but total_pages > 0 (e.g. page 0 has users)
             # This case means we might have deleted the last user on a page > 0, and page 0 has users.
             # Default to page 0
            current_page = 0
            start_index = current_page * SUBSCRIBERS_PER_PAGE
            end_index = start_index + SUBSCRIBERS_PER_PAGE
            page_subscriber_ids = all_subscriber_ids[start_index:end_index]


        if not page_subscriber_ids: # if still no subscribers for any valid page
            await query.message.edit_text(_("No subscribers found."))
            return

        new_keyboard = create_subscriber_list_keyboard(_, page_subscriber_ids, current_page, total_pages)
        await query.message.edit_text(
            _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                current_page_display=current_page + 1,
                total_pages=total_pages
            ), # SUBSCRIBERS_LIST_HEADER
            reply_markup=new_keyboard
        )

    elif action == "page":
        current_page = callback_data.page
        if current_page is None: # Should not happen if callback data is constructed correctly
            await query.answer("Error: Page number missing.", show_alert=True)
            return

        all_subscriber_ids = await get_all_subscribers_ids(session)
        if not all_subscriber_ids:
            await query.message.edit_text(_("No subscribers found.")) # SUBSCRIBERS_NONE_FOUND
            await query.answer()
            return

        total_pages = (len(all_subscriber_ids) + SUBSCRIBERS_PER_PAGE - 1) // SUBSCRIBERS_PER_PAGE

        # Ensure current_page is valid
        if current_page < 0:
            current_page = 0
        elif current_page >= total_pages:
            current_page = total_pages - 1


        start_index = current_page * SUBSCRIBERS_PER_PAGE
        end_index = start_index + SUBSCRIBERS_PER_PAGE
        page_subscriber_ids = all_subscriber_ids[start_index:end_index]

        if not page_subscriber_ids and total_pages > 0 : # current page is empty, but there are users (e.g. nav beyond last page)
            # this can happen if total_pages decreased and current_page is now out of bounds.
            # default to last valid page
            current_page = total_pages -1
            start_index = current_page * SUBSCRIBERS_PER_PAGE
            end_index = start_index + SUBSCRIBERS_PER_PAGE
            page_subscriber_ids = all_subscriber_ids[start_index:end_index]

        if not page_subscriber_ids: # If still no users for any valid page
            await query.message.edit_text(_("No subscribers found."))
            await query.answer()
            return


        keyboard = create_subscriber_list_keyboard(_, page_subscriber_ids, current_page, total_pages)
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
