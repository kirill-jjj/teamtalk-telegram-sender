import logging
import asyncio
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import get_all_subscribers_ids
from bot.services import user_service
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.callback_data import SubscriberListCallback
# SubscriberInfo is used by _get_paginated_subscribers_info, which is now in list_utils
# from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.utils import send_or_edit_paginated_list
from bot.core.enums import SubscriberListAction
from bot.state import ADMIN_IDS_CACHE
from .list_utils import _get_paginated_subscribers_info # Import from list_utils

logger = logging.getLogger(__name__)

# SUBSCRIBERS_PER_PAGE has been moved to list_utils.py
# _get_paginated_subscribers_info has been moved to list_utils.py

subscriber_list_router = Router(name="subscriber_list_actions_router")

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
