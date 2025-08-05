"""Callback query handlers for actions related to banned users."""

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import SubscriberAction
from bot.models import BanList
from bot.services import admin_service
from bot.telegram_bot.callback_data import SubscriberActionCallback
from bot.telegram_bot.handlers.callback_handlers.list_utils import (
    SUBSCRIBERS_PER_PAGE,
    _prepare_user_list,
    _show_subscriber_list_page,
)
from bot.telegram_bot.keyboards import create_banned_user_list_keyboard
from bot.telegram_bot.ui_utils import display_paginated_list

from ._helpers import action_and_refresh_view, ensure_message_context

if TYPE_CHECKING:
    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)
banned_user_actions_router = Router(name="banned_user_actions_router")


async def refresh_banned_list_view(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    **kwargs: object,
) -> None:
    """Refresher function for the banned user list view."""
    await _show_banned_list_page(
        target=query,
        session=session,
        services=services,
        page=callback_data.page,
        translator=translator,
    )


@banned_user_actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.UNBAN))
@ensure_message_context
@action_and_refresh_view(refresh_banned_list_view)
async def handle_unban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
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


async def _show_banned_list_page(
    target: CallbackQuery | Message,
    session: AsyncSession,
    services: "Services",
    page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Shows a paginated list of banned users using the generic list helper."""
    _ = translator.gettext

    statement = select(BanList)

    def extractor(ban_entry: BanList) -> tuple[int, str | None] | None:
        # We must ensure telegram_id is not None, as the list is of users.
        # This should be guaranteed by how bans are created.
        if ban_entry.telegram_id is None:
            # This case should ideally not happen if data is consistent.
            # Log an error and skip the entry.
            logger.error("BanList entry with id %s has null telegram_id.", ban_entry.id)
            return None  # Returning None to be filtered out later
        return ban_entry.telegram_id, ban_entry.teamtalk_username

    # Filter out entries with no telegram_id before passing to the preparer
    statement = statement.where(BanList.telegram_id.isnot(None))  # type: ignore[union-attr]

    subscriber_infos = await _prepare_user_list(session, services.bot_event, statement, extractor)

    await display_paginated_list(
        target=target,
        bot=services.bot_event,
        translator=translator,
        items=subscriber_infos,
        page=page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
        page_size=SUBSCRIBERS_PER_PAGE,
    )


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
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


@banned_user_actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.BAN))
@ensure_message_context
@action_and_refresh_view(refresh_subscriber_list_view)
async def handle_ban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
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
