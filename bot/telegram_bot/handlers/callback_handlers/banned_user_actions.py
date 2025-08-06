"""Callback query handlers for actions related to banned users."""

from gettext import NullTranslations
import logging
from typing import Annotated

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberCommand
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.services.moderation_service import ModerationService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import SubscriberCallback
from bot.telegram_bot.handlers.callback_handlers.list_utils import (
    _show_banned_list_page,
    _show_subscriber_list_page,
)
from bot.telegram_bot.types.bots import EventBot

from ._helpers import ensure_message_context, with_view_refresh

logger = logging.getLogger(__name__)
banned_user_actions_router = Router(name="banned_user_actions_router")


async def refresh_banned_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: NullTranslations,
    bot: EventBot,
    ban_repo: BanRepository,
    **kwargs: object,
) -> None:
    """Refresher function for the banned user list view."""
    await _show_banned_list_page(
        target=query,
        ban_repo=ban_repo,
        bot=bot,
        page=callback_data.page,
        translator=translator,
    )


@banned_user_actions_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.UNBAN))
@ensure_message_context
@with_view_refresh(refresh_banned_list_view)
async def unban_subscriber(
    callback_data: SubscriberCallback,
    translator: Annotated[NullTranslations, FromDishka()],
    moderation_service: Annotated[ModerationService, FromDishka()],
) -> tuple[bool, str, None]:
    """Handles unbanning a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await moderation_service.unban_subscriber(target_telegram_id)
    message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, message, None


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
    await _show_subscriber_list_page(
        target=query,
        user_repo=user_repo,
        subscriber_repo=subscriber_repo,
        bot=bot,
        translator=translator,
        page=callback_data.page,
    )


@banned_user_actions_router.callback_query(SubscriberCallback.filter(F.action == SubscriberCommand.BAN))
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def ban_subscriber(
    callback_data: SubscriberCallback,
    translator: Annotated[NullTranslations, FromDishka()],
    moderation_service: Annotated[ModerationService, FromDishka()],
    tt_connection: "TeamTalkConnection | None",
) -> tuple[bool, str, None]:
    """Handles banning and deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await moderation_service.ban_and_delete_subscriber(
        target_telegram_id, translator, tt_connection
    )

    if result.long_message:
        logger.info("Ban/delete report for %s:\n%s", target_telegram_id, result.long_message)

    short_message = _(result.message_key).format(**(result.message_args or {}))
    return result.success, short_message, None
