"""Callback query handlers for displaying and paginating the list of subscribers."""

from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberListAction
from bot.database.uow import IUnitOfWork
from bot.services.report_service import ReportService
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_subscriber_list_keyboard
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list

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
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles pagination for the subscriber list."""
    _ = translator.gettext

    async with uow:
        result = await report_service.get_subscribers_info(
            uow, page=callback_data.page or 0
        )

    await display_paginated_list(
        target=query,
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},
    )
