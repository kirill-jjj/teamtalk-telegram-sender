"""Callback query handlers for actions related to banned users."""

import gettext
import logging
from typing import TYPE_CHECKING, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import SubscriberAction
from bot.database import crud
from bot.services import admin_service
from bot.telegram_bot.callback_data import SubscriberActionCallback
from bot.telegram_bot.keyboards import create_banned_user_list_keyboard
from bot.telegram_bot.models import SubscriberInfo
from bot.telegram_bot.ui_utils import display_paginated_list
from bot.telegram_bot.utils import get_display_names_for_ids

from ._helpers import ensure_message_context
from .list_utils import (
    SUBSCRIBERS_PER_PAGE,
    _show_subscriber_list_page,
)

if TYPE_CHECKING:
    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)
banned_user_actions_router = Router(name="banned_user_actions_router")


@banned_user_actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.UNBAN))
@ensure_message_context
async def handle_unban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
) -> None:
    """Handles unbanning a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    result_message = await admin_service.unban_subscriber(
        session, services, tt_connection, target_telegram_id, translator
    )
    await query.answer(result_message, show_alert=True)
    await _show_banned_list_page(
        target=query, session=session, services=services, page=return_page, translator=translator
    )


async def _show_banned_list_page(
    target: CallbackQuery | Message,
    session: AsyncSession,
    services: "Services",
    page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Shows a paginated list of banned users."""
    _ = translator.gettext
    banned_users = await crud.get_all_banned_users(session)
    banned_user_ids = [bu.telegram_id for bu in banned_users if bu.telegram_id]

    display_names = await get_display_names_for_ids(services.bot_event, banned_user_ids)

    subscriber_infos = [
        SubscriberInfo(
            telegram_id=bu.telegram_id,
            display_name=display_names.get(bu.telegram_id, str(bu.telegram_id)),
            teamtalk_username=bu.teamtalk_username,
        )
        for bu in banned_users
        if bu.telegram_id
    ]

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


@banned_user_actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.BAN))
@ensure_message_context
async def handle_ban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: "TeamTalkConnection | None",
) -> None:
    """Handles banning a subscriber."""
    # The ensure_message_context decorator guarantees query.message is not None.
    message = cast(Message, query.message)
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    short_alert_message, long_report_message = await admin_service.ban_and_delete_subscriber(
        session, services, target_telegram_id, tt_connection
    )

    # Show a concise message in the alert popup.
    await query.answer(short_alert_message, show_alert=True)

    # Post the detailed report as a new message in the chat for the admin to review.
    await message.answer(long_report_message)

    # After banning and deleting, refresh the subscriber list to show the user is gone.
    await _show_subscriber_list_page(
        target=query,
        session=session,
        bot=services.bot_event,
        translator=translator,
        page=return_page,
    )
