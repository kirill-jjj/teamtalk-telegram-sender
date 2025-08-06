"""Callback query handlers for displaying and paginating the list of subscribers."""

from gettext import NullTranslations
import logging

from aiogram import Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import SubscriberListAction
from bot.services import user_service
from bot.services.cache_service import CacheService
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.types.bots import EventBot

from ._helpers import ensure_message_context
from .list_utils import _show_subscriber_list_page

logger = logging.getLogger(__name__)

subscriber_list_router = Router(name="subscriber_list_actions_router")


@subscriber_list_router.callback_query(SubscriberListCallback.filter())
@ensure_message_context
async def on_subscriber_list_callback(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    session: FromDishka[AsyncSession],
    translator: FromDishka[NullTranslations],
    cache: FromDishka[CacheService],
    bot: FromDishka[EventBot],
) -> None:
    """Handles actions from the subscriber list, like deletion or pagination."""
    _ = translator.gettext
    action = callback_data.action
    page_from_callback = callback_data.page if callback_data.page is not None else 0

    if action == SubscriberListAction.DELETE_SUBSCRIBER:
        if callback_data.telegram_id is None:
            await query.answer(_("Error: No Telegram ID specified for deletion."), show_alert=True)
            return

        telegram_id_to_delete = callback_data.telegram_id
        success = await user_service.delete_user_profile(session, telegram_id_to_delete, cache=cache)

        if success:
            await query.answer(
                _("Subscriber {telegram_id} deleted successfully.").format(telegram_id=telegram_id_to_delete)
            )
        else:
            await query.answer(
                _("Error deleting subscriber {telegram_id}.").format(telegram_id=telegram_id_to_delete),
                show_alert=True,
            )

        await _show_subscriber_list_page(query, session, bot, translator, page=page_from_callback)

    elif action == SubscriberListAction.PAGE:
        requested_page = callback_data.page
        if requested_page is None:
            await query.answer(_("Error: Page number missing."), show_alert=True)
            return

        await _show_subscriber_list_page(query, session, bot, translator, page=requested_page)
    else:
        logger.warning("Unhandled SubscriberListAction: %s from user %s", action, query.from_user.id)
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
