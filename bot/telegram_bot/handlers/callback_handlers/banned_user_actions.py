"""Callback query handlers for actions related to banned users."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberCommand
from bot.database.uow import IUnitOfWork
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.telegram_bot.callback_data import SubscriberCallback
from bot.telegram_bot.handlers.decorators import (
    ensure_message_context,
    with_view_refresh,
)
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list

logger = logging.getLogger(__name__)
banned_user_actions_router = Router(name="banned_user_actions_router")


async def refresh_banned_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: NullTranslations,
    bot: EventBot,
    report_service: ReportService,
    uow: IUnitOfWork,
    **kwargs: object,
) -> None:
    """Refresher function for the banned user list view."""
    _ = translator.gettext

    result = await report_service.get_banned_users_info(uow, page=callback_data.page)

    await display_paginated_list(
        target=query,
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
    )


@banned_user_actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.UNBAN)
)
@ensure_message_context
@with_view_refresh(refresh_banned_list_view)
async def unban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: Annotated[NullTranslations, FromDishka()],
    moderation_service: Annotated[ModerationService, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> tuple[bool, str, None]:
    """Handles unbanning a subscriber."""
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        result = await moderation_service.unban_subscriber(
            uow, target_telegram_id, translator
        )
        await uow.commit()
    message = result.message_key.format(**(result.message_args or {}))
    return result.success, message, None


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: NullTranslations,
    bot: EventBot,
    report_service: ReportService,
    uow: IUnitOfWork,
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    _ = translator.gettext

    result = await report_service.get_subscribers_info(uow, page=callback_data.page)

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


@banned_user_actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.BAN)
)
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def ban_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: Annotated[NullTranslations, FromDishka()],
    moderation_service: Annotated[ModerationService, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> tuple[bool, str, None]:
    """Handles banning a subscriber."""
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        result = await moderation_service.ban_subscriber(
            uow, target_telegram_id, translator
        )
        await uow.commit()

    if result.long_message:
        logger.info("Ban report for %s:\n%s", target_telegram_id, result.long_message)

    short_message = result.message_key.format(**(result.message_args or {}))
    return result.success, short_message, None
