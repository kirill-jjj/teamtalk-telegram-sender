"""Callback query handlers for displaying and paginating the list of subscribers."""

from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberListAction
from bot.services.report_service import ReportService
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import _show_subscriber_list_page

logger = logging.getLogger(__name__)

subscriber_list_router = Router(name="subscriber_list_actions_router")


@subscriber_list_router.callback_query(
    SubscriberListCallback.filter(F.action == SubscriberListAction.PAGE)
)
@ensure_message_context
async def on_subscriber_list_page(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
) -> None:
    """Handles pagination for the subscriber list."""
    await _show_subscriber_list_page(
        query,
        report_service,
        bot,
        translator,
        page=callback_data.page or 0,
    )
    await query.answer()
