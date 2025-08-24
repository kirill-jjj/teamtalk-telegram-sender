"""Callback query handlers for core actions related to specific subscribers."""

from gettext import NullTranslations
import logging
from typing import cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberCommand, SubscriberListAction
from bot.database.uow import IUnitOfWork
from bot.models import UserSettings
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.api import get_display_name_for_id
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberCallback,
    SubscriberListCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.formatters import format_subscriber_details
from bot.telegram_bot.handlers.decorators import (
    ensure_message_context,
    with_view_refresh,
)
from bot.telegram_bot.keyboards import create_subscriber_action_menu_keyboard
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import (
    _show_subscriber_list_page,
)

logger = logging.getLogger(__name__)
actions_router = Router(name="subscriber_management.actions_router")


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    user_settings: UserSettings,
    translator: NullTranslations,
    bot: "EventBot",
) -> None:
    """Helper function to display the subscriber details view."""
    _ = translator.gettext

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    display_name = await get_display_name_for_id(bot, user_settings.telegram_id)
    text = format_subscriber_details(user_settings, display_name, translator)

    # This assumes query.message is a Message, which is guaranteed by
    # @ensure_message_context
    await cast(Message, query.message).edit_text(
        text, reply_markup=keyboard, parse_mode="HTML"
    )
    await query.answer()


async def refresh_subscriber_view(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberNotificationPrefCallback
    | AdminSetSubscriberMuteModeCallback
    | SubscriberCallback,
    translator: NullTranslations,
    bot: "EventBot",
    **kwargs: object,
) -> None:
    """Refresher function for the subscriber detail view."""
    target_telegram_id = callback_data.target_telegram_id
    page_context = getattr(
        callback_data, "subscriber_page_context", getattr(callback_data, "page", 0)
    )

    user_settings: UserSettings | None = cast(UserSettings, kwargs.get("user_settings"))
    if not user_settings:
        logger.error(
            "refresh_subscriber_view called without 'user_settings' in kwargs for TG ID %s",
            target_telegram_id,
        )
        await query.answer("Internal error: User settings not found.", show_alert=True)
        return

    await _display_subscriber_view(
        query=query,
        target_telegram_id=target_telegram_id,
        page_context=page_context,
        user_settings=user_settings,
        translator=translator,
        bot=bot,
    )


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    report_service: ReportService,
    bot: EventBot,
    return_page: int,
    translator: NullTranslations,
) -> None:
    """Refresh and display paginated subscribers list via the central display func."""
    await _show_subscriber_list_page(
        target=query,
        report_service=report_service,
        bot=bot,
        translator=translator,
        page=return_page,
    )


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: NullTranslations,
    bot: EventBot,
    uow: IUnitOfWork,
    report_service: ReportService,
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    await _refresh_and_display_subscriber_list(
        query=query,
        report_service=report_service,
        bot=bot,
        return_page=callback_data.page,
        translator=translator,
    )


@actions_router.callback_query(
    SubscriberListCallback.filter(F.action == SubscriberListAction.DELETE_SUBSCRIBER)
)
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def delete_subscriber_from_list(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    translator: FromDishka[NullTranslations],
    subscription_service: FromDishka[SubscriptionService],
    report_service: FromDishka[ReportService],
    uow: FromDishka[IUnitOfWork],
) -> tuple[bool, str, None]:
    """Handles deleting a subscriber directly from the subscriber list."""
    _ = translator.gettext

    if callback_data.telegram_id is None:
        return False, _("Error: No Telegram ID specified for deletion."), None

    target_telegram_id = callback_data.telegram_id

    async with uow:
        result = await subscription_service.delete_profile(
            target_telegram_id, translator, uow=uow
        )

    message = result.message_key.format(**(result.message_args or {}))

    return result.success, message, None


@actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.BAN)
)
@ensure_message_context
@with_view_refresh(refresh_subscriber_list_view)
async def on_ban_subscriber_confirm(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    moderation_service: FromDishka[ModerationService],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
    uow: FromDishka[IUnitOfWork],
) -> tuple[bool, str, None]:
    """Handles banning and deleting a subscriber after admin confirmation."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        result = await moderation_service.ban_and_delete_subscriber(
            target_telegram_id, translator, uow=uow
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
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    subscription_service: FromDishka[SubscriptionService],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
    uow: FromDishka[IUnitOfWork],
) -> tuple[bool, str, None]:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    # Pass uow to the service to avoid session conflicts
    async with uow:
        result = await subscription_service.delete_profile(
            target_telegram_id, translator, uow=uow
        )

    message = result.message_key.format(**(result.message_args or {}))

    return result.success, message, None


@actions_router.callback_query(ViewSubscriberCallback.filter())
@ensure_message_context
async def view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Handle viewing details and actions for a subscriber via the display helper."""
    user_settings = await user_settings_service.get_or_create(
        callback_data.telegram_id,
        "en",  # lang doesn't matter here
    )
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
