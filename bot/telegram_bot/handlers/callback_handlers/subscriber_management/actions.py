"""Callback query handlers for core actions related to specific subscribers."""

from gettext import NullTranslations
import logging
from typing import cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberCommand, SubscriberListAction
from bot.database.uow import IUnitOfWork
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO, SubscriberViewData
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberCallback,
    SubscriberListCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.formatters import format_subscriber_details
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import (
    create_subscriber_action_menu_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list

logger = logging.getLogger(__name__)
actions_router = Router(name="subscriber_management.actions_router")


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    view_data: SubscriberViewData,
    translator: NullTranslations,
) -> None:
    """Helper function to display the subscriber details view."""
    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    # The user_settings object is now nested inside the view_data DTO
    user_settings_dto = SettingsViewDTO(
        language_code=view_data.user_settings.language_code,
        notification_settings=view_data.user_settings.notification_settings,
        mute_list_mode=view_data.user_settings.mute_list_mode,
        not_on_online_enabled=view_data.user_settings.not_on_online_enabled,
        teamtalk_username=view_data.user_settings.teamtalk_username,
        muted_users_count=len(view_data.user_settings.muted_users_list),
    )
    text = format_subscriber_details(
        user_settings_dto, view_data.display_name, translator
    )

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
    user_settings_service: UserSettingsService,  # Add service
    uow: IUnitOfWork,
    **kwargs: object,
) -> None:
    """Refresher function for the subscriber detail view."""
    target_telegram_id = callback_data.target_telegram_id
    page_context = getattr(
        callback_data, "subscriber_page_context", getattr(callback_data, "page", 0)
    )

    # Fetch the full view data DTO from the service
    view_data = await user_settings_service.get_subscriber_view_data(
        uow,
        target_telegram_id,
        "en",  # lang doesn't matter here
        bot,
    )
    if not view_data:
        logger.error(
            "refresh_subscriber_view could not fetch view_data for TG ID %s",
            target_telegram_id,
        )
        await query.answer("Internal error: User settings not found.", show_alert=True)
        return

    await _display_subscriber_view(
        query=query,
        target_telegram_id=target_telegram_id,
        page_context=page_context,
        view_data=view_data,
        translator=translator,
    )


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    report_service: ReportService,
    bot: EventBot,
    return_page: int,
    translator: NullTranslations,
) -> None:
    """Refresh and display paginated subscribers list via the central display func."""
    _ = translator.gettext

    result = await report_service.get_subscribers_info(page=return_page)

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


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback | SubscriberListCallback,
    translator: NullTranslations,
    bot: EventBot,
    report_service: ReportService,
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    await _refresh_and_display_subscriber_list(
        query=query,
        report_service=report_service,
        bot=bot,
        return_page=callback_data.page or 0,
        translator=translator,
    )


@actions_router.callback_query(
    SubscriberListCallback.filter(F.action == SubscriberListAction.DELETE_SUBSCRIBER)
)
@ensure_message_context
async def delete_subscriber_from_list(
    query: CallbackQuery,
    callback_data: SubscriberListCallback,
    translator: FromDishka[NullTranslations],
    subscription_service: FromDishka[SubscriptionService],
    report_service: FromDishka[ReportService],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles deleting a subscriber directly from the subscriber list."""
    _ = translator.gettext

    if callback_data.telegram_id is None:
        await query.answer(
            _("Error: No Telegram ID specified for deletion."), show_alert=True
        )
        return
    target_telegram_id = callback_data.telegram_id

    result = await subscription_service.delete_profile(
        uow, target_telegram_id, translator
    )

    message = result.message_key.format(**(result.message_args or {}))
    await query.answer(message, show_alert=True)

    if result.success:
        await refresh_subscriber_list_view(
            query,
            callback_data,
            translator,
            bot,
            report_service=report_service,
        )


@actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.BAN)
)
@ensure_message_context
async def on_ban_subscriber_confirm(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    moderation_service: FromDishka[ModerationService],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles banning a subscriber after admin confirmation."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        result = await moderation_service.ban_subscriber(
            uow, target_telegram_id, translator
        )
        await uow.commit()

    if result.long_message:
        logger.info("Ban report for %s:\n%s", target_telegram_id, result.long_message)

    short_message = _(result.message_key).format(**(result.message_args or {}))

    await query.answer(short_message, show_alert=True)

    if result.success:
        await refresh_subscriber_list_view(
            query,
            callback_data,
            translator,
            bot,
            report_service=report_service,
        )


@actions_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.DELETE)
)
@ensure_message_context
async def delete_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    subscription_service: FromDishka[SubscriptionService],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    result = await subscription_service.delete_profile(
        uow, target_telegram_id, translator
    )

    message = result.message_key.format(**(result.message_args or {}))
    await query.answer(message, show_alert=True)

    if result.success:
        await refresh_subscriber_list_view(
            query,
            callback_data,
            translator,
            bot,
            report_service=report_service,
        )


@actions_router.callback_query(ViewSubscriberCallback.filter())
@ensure_message_context
async def view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handle viewing details and actions for a subscriber via the display helper."""
    _ = translator.gettext
    async with uow:
        view_data = await user_settings_service.get_subscriber_view_data(
            uow,
            callback_data.telegram_id,
            "en",  # lang doesn't matter here
            bot,
        )
    if not view_data:
        await query.answer(_("User not found."), show_alert=True)
        return

    await _display_subscriber_view(
        query=query,
        target_telegram_id=callback_data.telegram_id,
        page_context=callback_data.page,
        view_data=view_data,
        translator=translator,
    )
