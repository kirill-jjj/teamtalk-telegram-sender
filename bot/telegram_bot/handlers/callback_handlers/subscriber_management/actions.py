"""Callback query handlers for core actions related to specific subscribers."""

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import SubscriberAction
from bot.services import admin_service, user_service
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    SubscriberActionCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.handlers.callback_handlers._helpers import (
    _display_subscriber_view,
    action_and_refresh_view,
    ensure_message_context,
)
from bot.telegram_bot.handlers.callback_handlers.list_utils import (
    _show_subscriber_list_page,
)

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
actions_router = Router(name="subscriber_management.actions_router")


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    await _refresh_and_display_subscriber_list(
        query=query,
        session=session,
        services=services,
        return_page=callback_data.page,
        translator=translator,
    )


@actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.BAN))
@ensure_message_context
@action_and_refresh_view(refresh_subscriber_list_view)
async def on_ban_subscriber_confirm(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: TeamTalkConnection | None,
) -> tuple[bool, str]:
    """Handles banning and deleting a subscriber after admin confirmation."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await admin_service.ban_and_delete_subscriber(session, services, target_telegram_id, tt_connection)

    if result.long_message:
        logger.info("Ban/delete report for %s:\n%s", target_telegram_id, result.long_message)

    short_message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, short_message


@actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.DELETE))
@ensure_message_context
@action_and_refresh_view(refresh_subscriber_list_view)
async def handle_delete_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: TeamTalkConnection | None,  # Injected by middleware, unused
) -> tuple[bool, str]:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    success = await user_service.delete_full_user_profile(session, target_telegram_id, services=services)

    if success:
        message = _("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id)
    else:
        message = _("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id)

    return success, message


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    services: "Services",
    return_page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Refreshes and displays the paginated list of subscribers by calling the central list display function."""
    _ = translator.gettext
    if not services.bot_event:
        logger.error("_refresh_and_display_subscriber_list: services.bot_event is not available.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    await _show_subscriber_list_page(
        target=query,
        session=session,
        bot=services.bot_event,
        translator=translator,
        page=return_page,
    )


@actions_router.callback_query(ViewSubscriberCallback.filter())
@ensure_message_context
async def handle_view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles viewing details and actions for a specific subscriber by calling the display helper."""
    await _display_subscriber_view(
        query=query,
        target_telegram_id=callback_data.telegram_id,
        page_context=callback_data.page,
        session=session,
        translator=translator,
        services=services,
    )
