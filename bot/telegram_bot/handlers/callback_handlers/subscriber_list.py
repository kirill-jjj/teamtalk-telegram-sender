import logging
# import asyncio # Not directly used here
from aiogram import Router, Bot as AiogramBot, F # Renamed Bot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services import user_service
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.utils import send_or_edit_paginated_list
from bot.core.enums import SubscriberListAction
from .list_utils import _show_subscriber_list_page

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)

subscriber_list_router = Router(name="subscriber_list_actions_router")

# Removed F.from_user.id.in_(ADMIN_IDS_CACHE) filter
@subscriber_list_router.callback_query(SubscriberListCallback.filter())
async def handle_subscriber_list_actions(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    session: AsyncSession,
    bot: AiogramBot,
    _: callable,
    app: "Application"
):
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    action = callback_data.action
    page_from_callback = callback_data.page if callback_data.page is not None else 0

    if action == SubscriberListAction.DELETE_SUBSCRIBER:
        if callback_data.telegram_id is None:
            await query.answer(_("Error: No Telegram ID specified for deletion."), show_alert=True)
            return

        telegram_id_to_delete = callback_data.telegram_id
        success = await user_service.delete_full_user_profile(session, telegram_id_to_delete, app=app)

        if success:
            await query.answer(_("Subscriber {telegram_id} deleted successfully.").format(telegram_id=telegram_id_to_delete))
        else:
            await query.answer(_("Error deleting subscriber {telegram_id}.").format(telegram_id=telegram_id_to_delete), show_alert=True)

        await _show_subscriber_list_page(query, session, bot, _, page=page_from_callback)

    elif action == SubscriberListAction.PAGE:
        requested_page = callback_data.page
        if requested_page is None:
            await query.answer(_("Error: Page number missing."), show_alert=True)
            return

        await _show_subscriber_list_page(query, session, bot, _, page=requested_page)
    else:
        logger.warning(f"Unhandled SubscriberListAction: {action} from user {query.from_user.id}")
        await query.answer(_("Unknown action."), show_alert=True)
