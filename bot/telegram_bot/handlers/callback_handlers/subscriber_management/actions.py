"""Callback query handlers for core actions related to specific subscribers."""

from gettext import NullTranslations
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.callback_answer import CallbackAnswer
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberCommand
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.services.moderation_service import ModerationService
from bot.services.subscription_service import SubscriptionService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    SubscriberCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.handlers.callback_handlers._helpers import (
    _display_subscriber_view,
    ensure_message_context,
    with_view_refresh,
)
from bot.telegram_bot.handlers.callback_handlers.list_utils import (
    _show_subscriber_list_page,
)
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)
actions_router = Router(name="subscriber_management.actions_router")


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: NullTranslations,
    bot: EventBot,
    user_repo: UserRepository,
    subscriber_repo: SubscriberRepository,
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    await _refresh_and_display_subscriber_list(
        query=query,
        user_repo=user_repo,
        subscriber_repo=subscriber_repo,
        bot=bot,
        return_page=callback_data.page,
        translator=translator,
    )


@actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.BAN)
)
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def on_ban_subscriber_confirm(
    query: CallbackQuery,
    callback_answer: CallbackAnswer,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    moderation_service: FromDishka[ModerationService],
    tt_connection: TeamTalkConnection | None,
) -> tuple[bool, str, None]:
    """Handles banning and deleting a subscriber after admin confirmation."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await moderation_service.ban_and_delete_subscriber(
        target_telegram_id, translator, tt_connection
    )

    if result.long_message:
        logger.info(
            "Ban/delete report for %s:\n%s", target_telegram_id, result.long_message
        )

    short_message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, short_message, None


@actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.DELETE)
)
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def delete_subscriber(
    query: CallbackQuery,
    callback_answer: CallbackAnswer,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    subscription_service: FromDishka[SubscriptionService],
) -> tuple[bool, str, None]:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    success = await subscription_service.delete_profile(target_telegram_id)

    if success:
        message = _("Subscriber {telegram_id} deleted successfully.").format(
            telegram_id=target_telegram_id
        )
    else:
        message = _("Error deleting subscriber {telegram_id}.").format(
            telegram_id=target_telegram_id
        )

    return success, message, None


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    user_repo: UserRepository,
    subscriber_repo: SubscriberRepository,
    bot: EventBot,
    return_page: int,
    translator: NullTranslations,
) -> None:
    """Refresh and display paginated subscribers list via the central display func."""
    await _show_subscriber_list_page(
        target=query,
        user_repo=user_repo,
        subscriber_repo=subscriber_repo,
        bot=bot,
        translator=translator,
        page=return_page,
    )


@actions_router.callback_query(ViewSubscriberCallback.filter())
@ensure_message_context
async def view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_repo: FromDishka[UserRepository],
) -> None:
    """Handle viewing details and actions for a subscriber via the display helper."""
    user_settings = await user_repo.get_by_id(callback_data.telegram_id)
    if not user_settings:
        await query.answer("User not found.", show_alert=True)
        return

    await _display_subscriber_view(
        query=query,
        target_telegram_id=callback_data.telegram_id,
        page_context=callback_data.page,
        user_settings=user_settings,
        translator=translator,
        bot=bot,
    )
