"""Callback query handlers for displaying and paginating the list of subscribers."""

from gettext import NullTranslations
import logging
from typing import Any

from aiogram import Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberListAction
from bot.database.uow import IUnitOfWork
from bot.services.subscription_service import SubscriptionService
from bot.telegram_bot.callback_data import SubscriberListCallback
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.types.bots import EventBot

from .list_utils import _show_subscriber_list_page

logger = logging.getLogger(__name__)

subscriber_list_router = Router(name="subscriber_list_actions_router")


@subscriber_list_router.callback_query(SubscriberListCallback.filter())
@ensure_message_context
async def on_subscriber_list_callback(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    subscription_service: FromDishka[SubscriptionService],
    uow: FromDishka[IUnitOfWork],
    **kwargs: Any,  # noqa: ANN401
) -> None:
    """Handles actions from the subscriber list, like deletion or pagination."""
    callback_answer = kwargs["callback_answer"]
    _ = translator.gettext
    action = callback_data.action
    page_from_callback = callback_data.page if callback_data.page is not None else 0

    async with uow:
        if action == SubscriberListAction.DELETE_SUBSCRIBER:
            if callback_data.telegram_id is None:
                callback_answer.text = _(
                    "Error: No Telegram ID specified for deletion."
                )
                callback_answer.show_alert = True
                return

            telegram_id_to_delete = callback_data.telegram_id
            success = await subscription_service.delete_profile(telegram_id_to_delete)

            if success:
                callback_answer.text = _(
                    "Subscriber {telegram_id} deleted successfully."
                ).format(telegram_id=telegram_id_to_delete)
            else:
                callback_answer.text = _(
                    "Error deleting subscriber {telegram_id}."
                ).format(telegram_id=telegram_id_to_delete)
                callback_answer.show_alert = True

            await _show_subscriber_list_page(
                query,
                uow.users,
                uow.subscribers,
                bot,
                translator,
                page=page_from_callback,
            )

        elif action == SubscriberListAction.PAGE:
            requested_page = callback_data.page
            if requested_page is None:
                callback_answer.text = _("Error: Page number missing.")
                callback_answer.show_alert = True
                return

            await _show_subscriber_list_page(
                query, uow.users, uow.subscribers, bot, translator, page=requested_page
            )
        else:
            logger.warning(
                "Unhandled SubscriberListAction: %s from user %s",
                action,
                query.from_user.id,
            )
            callback_answer.text = _("An error occurred. Please try again later.")
            callback_answer.show_alert = True
