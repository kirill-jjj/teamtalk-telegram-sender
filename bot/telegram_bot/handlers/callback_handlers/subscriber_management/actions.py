"""Callback query handlers for core actions related to specific subscribers."""
from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any, TypeAlias, cast

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from aiogram.utils.callback_answer import CallbackAnswer
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import SubscriberCommand
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.database.uow import IUnitOfWork
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.services.moderation_service import ModerationService
from bot.services.subscription_service import SubscriptionService
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.formatters import format_telegram_user_display_name
from bot.telegram_bot.handlers.callback_handlers.list_utils import (
    _show_subscriber_list_page,
)
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_subscriber_action_menu_keyboard
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)
actions_router = Router(name="subscriber_management.actions_router")


RefreshableViewCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberNotificationPrefCallback
    | AdminSetSubscriberMuteModeCallback
    | SubscriberCallback
)


ViewRefresher: TypeAlias = Callable[..., Awaitable[None]]


def with_view_refresh(
    view_refresher: ViewRefresher,
) -> Callable[
    [Callable[..., Awaitable[tuple[bool, str, Any | None]]]],
    Callable[..., Awaitable[None]],
]:
    """Decorator factory for actions that result in refreshing a view.

    The decorated function MUST return a tuple: (success, message, updated_object).
    """

    def decorator(
        func: Callable[..., Awaitable[tuple[bool, str, Any | None]]],
    ) -> Callable[..., Awaitable[None]]:
        @functools.wraps(func)
        async def wrapper(
            query: CallbackQuery,
            callback_answer: CallbackAnswer,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> None:
            """Wrapper function for the with_view_refresh decorator."""
            success, message, updated_object = await func(
                query, callback_answer, *args, **kwargs
            )

            callback_answer.text = message
            callback_answer.show_alert = not success

            if updated_object and isinstance(updated_object, UserSettings):
                kwargs["user_settings"] = updated_object
                if "translator_factory" in kwargs:
                    translator_factory = kwargs["translator_factory"]
                    new_translator = translator_factory(updated_object.language_code)
                    kwargs["translator"] = new_translator

            await view_refresher(
                query,
                *args,
                **kwargs,
            )

        return wrapper

    return decorator


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
    display_name = str(target_telegram_id)

    try:
        chat_info = await bot.get_chat(user_settings.telegram_id)
        display_name = format_telegram_user_display_name(chat_info)
    except TelegramAPIError:
        logger.exception(
            "Could not fetch chat info for %s via Telegram API.",
            user_settings.telegram_id,
        )
    except Exception:
        logger.exception(
            "Unexpected error fetching chat info for %s.", user_settings.telegram_id
        )

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    details_parts.append(
        _("Linked TT Account: {tt_username}").format(
            tt_username=user_settings.teamtalk_username or _("None")
        )
    )
    details_parts.append(_("Language: {lang}").format(lang=user_settings.language_code))
    noon_status = _("Enabled") if user_settings.not_on_online_enabled else _("Disabled")
    details_parts.append(_("NOON (Not on Online): {status}").format(status=noon_status))
    notif_setting_map = {
        NotificationSetting.ALL.value: _("All (Join & Leave)"),
        NotificationSetting.LEAVE_OFF.value: _("Join Only"),
        NotificationSetting.JOIN_OFF.value: _("Leave Only"),
        NotificationSetting.NONE.value: _("None"),
    }
    notif_setting_str = user_settings.notification_settings.value
    details_parts.append(
        _("Notifications: {setting}").format(
            setting=notif_setting_map.get(notif_setting_str, notif_setting_str)
        )
    )
    mute_mode_str = (
        _("Blacklist")
        if user_settings.mute_list_mode == MuteListMode.blacklist
        else _("Whitelist")
    )
    details_parts.append(_("Mute Mode: {mode}").format(mode=mute_mode_str))

    text = "\n".join(details_parts)
    # This assumes query.message is a Message, which is guaranteed by
    # @ensure_message_context
    await cast(Message, query.message).edit_text(
        text, reply_markup=keyboard, parse_mode="HTML"
    )
    await query.answer()


async def refresh_subscriber_view(
    query: CallbackQuery,
    callback_data: RefreshableViewCallback,
    translator: NullTranslations,
    bot: "EventBot",
    uow: IUnitOfWork,
    **kwargs: object,
) -> None:
    """Refresher function for the subscriber detail view."""
    target_telegram_id = callback_data.target_telegram_id
    page_context = getattr(
        callback_data, "subscriber_page_context", getattr(callback_data, "page", 0)
    )

    async with uow:
        user_settings = await uow.users.get_by_id(target_telegram_id)
        if not user_settings:
            await query.answer("User not found.", show_alert=True)
            return

        await _display_subscriber_view(
            query=query,
            target_telegram_id=target_telegram_id,
            page_context=page_context,
            user_settings=user_settings,
            translator=translator,
            bot=bot,
        )


async def refresh_subscriber_list_view(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: NullTranslations,
    bot: EventBot,
    uow: IUnitOfWork,
    **kwargs: object,
) -> None:
    """Refresher function for the main subscriber list view."""
    await _refresh_and_display_subscriber_list(
        query=query,
        user_repo=uow.users,
        subscriber_repo=uow.subscribers,
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
    bot: FromDishka[EventBot],
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
    callback_answer: CallbackAnswer,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    subscription_service: FromDishka[SubscriptionService],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
) -> tuple[bool, str, None]:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    # Передаем uow в сервис, чтобы избежать конфликта сессий
    success = await subscription_service.delete_profile(target_telegram_id, uow=uow)

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
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handle viewing details and actions for a subscriber via the display helper."""
    async with uow:
        user_settings = await uow.users.get_by_id(callback_data.telegram_id)
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
