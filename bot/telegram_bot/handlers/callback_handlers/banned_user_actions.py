"""Callback query handlers for actions related to banned users."""

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import SubscriberCommand
from bot.services import admin_service
from bot.telegram_bot.callback_data import SubscriberCallback
from bot.telegram_bot.handlers.callback_handlers.list_utils import (
    _show_banned_list_page,
    _show_subscriber_list_page,
)

from ._helpers import ensure_message_context, with_view_refresh

if TYPE_CHECKING:
    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)
banned_user_actions_router = Router(name="banned_user_actions_router")


async def refresh_banned_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    **kwargs: object,
) -> None:
    """Refresher function for the banned user list view."""
    await _show_banned_list_page(
        target=query,
        session=session,
        bot=services.bot_event,
        page=callback_data.page,
        translator=translator,
    )


@banned_user_actions_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.UNBAN))
@ensure_message_context
@with_view_refresh(refresh_banned_list_view)
async def unban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
) -> tuple[bool, str]:
    """Handles unbanning a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await admin_service.unban_subscriber(session, services, tt_connection, target_telegram_id)
    message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, message


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    if not services.bot_event:
        logger.error("refresh_subscriber_list_view: services.bot_event is not available.")
        await query.answer(translator.gettext("An error occurred. Please try again later."), show_alert=True)
        return

    await _show_subscriber_list_page(
        target=query,
        session=session,
        bot=services.bot_event,
        translator=translator,
        page=callback_data.page,
    )


@banned_user_actions_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.BAN))
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def ban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
) -> tuple[bool, str]:
    """Handles banning and deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await admin_service.ban_and_delete_subscriber(session, services, target_telegram_id, tt_connection)

    if result.long_message:
        logger.info("Ban/delete report for %s:\n%s", target_telegram_id, result.long_message)

    short_message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, short_message
