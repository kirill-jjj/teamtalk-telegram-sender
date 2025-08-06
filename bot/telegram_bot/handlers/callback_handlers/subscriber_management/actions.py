"""Callback query handlers for core actions related to specific subscribers."""

from gettext import NullTranslations
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import SubscriberCommand
from bot.services import admin_service, user_service
from bot.services.cache_service import CacheService
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

logger = logging.getLogger(__name__)
actions_router = Router(name="subscriber_management.actions_router")


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: NullTranslations,
    bot: Bot,
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    await _refresh_and_display_subscriber_list(
        query=query,
        session=session,
        bot=bot,
        return_page=callback_data.page,
        translator=translator,
    )


@actions_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.BAN))
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def on_ban_subscriber_confirm(
    callback_data: SubscriberCallback,
    session: FromDishka[AsyncSession],
    translator: FromDishka[NullTranslations],
    cache: FromDishka[CacheService],
    tt_connection: TeamTalkConnection | None,
) -> tuple[bool, str]:
    """Handles banning and deleting a subscriber after admin confirmation."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await admin_service.ban_and_delete_subscriber(
        session, cache, translator, target_telegram_id, tt_connection
    )

    if result.long_message:
        logger.info("Ban/delete report for %s:\n%s", target_telegram_id, result.long_message)

    short_message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, short_message


@actions_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.DELETE))
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def delete_subscriber(
    callback_data: SubscriberCallback,
    session: FromDishka[AsyncSession],
    translator: FromDishka[NullTranslations],
    cache: FromDishka[CacheService],
) -> tuple[bool, str]:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    success = await user_service.delete_user_profile(session, target_telegram_id, cache=cache)

    if success:
        message = _("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id)
    else:
        message = _("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id)

    return success, message


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    return_page: int,
    translator: NullTranslations,
) -> None:
    """Refreshes and displays the paginated list of subscribers by calling the central list display function."""
    await _show_subscriber_list_page(
        target=query,
        session=session,
        bot=bot,
        translator=translator,
        page=return_page,
    )


@actions_router.callback_query(ViewSubscriberCallback.filter())
@ensure_message_context
async def view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    session: FromDishka[AsyncSession],
    translator: FromDishka[NullTranslations],
    bot: FromDishka[Bot],
) -> None:
    """Handles viewing details and actions for a specific subscriber by calling the display helper."""
    await _display_subscriber_view(
        query=query,
        target_telegram_id=callback_data.telegram_id,
        page_context=callback_data.page,
        session=session,
        translator=translator,
        bot=bot,
    )
