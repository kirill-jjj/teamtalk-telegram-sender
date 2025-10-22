"""Callback query handlers for an admin managing a subscriber's settings."""

from collections.abc import Awaitable, Callable
from gettext import NullTranslations
import logging
from typing import TypeAlias, TypedDict

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka

from bot.constants import MUTE_LIST_ITEMS_PER_PAGE
from bot.core.enums import Actor, SubscriberCommand
from bot.core.languages import LanguageInfo
from bot.database.uow import IUnitOfWork
from bot.models import (
    MuteListMode,
    NotificationSetting,
    UserSettings,
)
from bot.services.schemas import SubscriberViewData
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    PaginateMuteListCallback,
    SubscriberCallback,
)
from bot.telegram_bot.handlers.callback_handlers.subscriber_management.actions import (
    refresh_subscriber_view,
)
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import (
    create_admin_subscriber_lang_keyboard,
    create_admin_subscriber_mute_mode_keyboard,
    create_admin_subscriber_notification_pref_keyboard,
    create_view_mute_list_keyboard,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_paginated_list


class SettingChoiceConfig(TypedDict):
    """A type hint for the setting choice configuration dictionary."""

    message_text: str
    keyboard_factory: "Callable[..., InlineKeyboardMarkup]"
    keyboard_factory_kwargs: dict[str, object]


logger = logging.getLogger(__name__)
settings_router = Router(name="subscriber_management.settings_router")


async def _present_subscriber_setting_choice(
    query: CallbackQuery,
    message_text: str,
    keyboard_factory: "Callable[..., InlineKeyboardMarkup]",
    keyboard_factory_kwargs: dict[str, object],
) -> None:
    """A generic helper to present a settings choice menu to an admin."""
    if isinstance(query.message, Message):
        keyboard = keyboard_factory(**keyboard_factory_kwargs)
        await query.message.edit_text(message_text, reply_markup=keyboard)
        await query.answer()


@settings_router.callback_query(
    SubscriberCallback.filter(
        F.action.in_(
            [
                SubscriberCommand.ADMIN_SET_LANGUAGE,
                SubscriberCommand.ADMIN_SET_NOTIF_PREF,
                SubscriberCommand.ADMIN_SET_MUTE_MODE,
            ]
        )
    )
)
@ensure_message_context
async def admin_set_setting_choice(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    available_languages: FromDishka[list[LanguageInfo]],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles showing the choice menu for various subscriber settings to an admin."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    action = callback_data.action

    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow, target_telegram_id, "en"
        )

    if not user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        return

    config_map: dict[SubscriberCommand, SettingChoiceConfig] = {
        SubscriberCommand.ADMIN_SET_LANGUAGE: {
            "message_text": _("Select new language for subscriber {tg_id}:").format(
                tg_id=target_telegram_id
            ),
            "keyboard_factory": create_admin_subscriber_lang_keyboard,
            "keyboard_factory_kwargs": {"available_languages": available_languages},
        },
        SubscriberCommand.ADMIN_SET_NOTIF_PREF: {
            "message_text": _(
                "Select notification preference for subscriber {tg_id}:"
            ).format(tg_id=target_telegram_id),
            "keyboard_factory": create_admin_subscriber_notification_pref_keyboard,
            "keyboard_factory_kwargs": {
                "current_setting": user_settings.notification_settings
            },
        },
        SubscriberCommand.ADMIN_SET_MUTE_MODE: {
            "message_text": _("Select mute list mode for subscriber {tg_id}:").format(
                tg_id=target_telegram_id
            ),
            "keyboard_factory": create_admin_subscriber_mute_mode_keyboard,
            "keyboard_factory_kwargs": {"current_mode": user_settings.mute_list_mode},
        },
    }

    config = config_map.get(action)
    if not config:
        logger.error("No config for action %s in admin_set_setting_choice", action)
        return

    common_kwargs = {
        "translator": translator,
        "target_telegram_id": target_telegram_id,
        "subscriber_page_context": callback_data.page,
    }
    await _present_subscriber_setting_choice(
        query,
        config["message_text"],
        config["keyboard_factory"],
        {**config["keyboard_factory_kwargs"], **common_kwargs},
    )


@settings_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.ADMIN_TOGGLE_NOON)
)
@ensure_message_context
async def admin_toggle_noon(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles an admin toggling NOON setting for a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        updated_settings = await user_settings_service.toggle_noon_setting(
            uow, target_telegram_id, actor=Actor.ADMIN
        )
        await uow.commit()

    if updated_settings:
        status = (
            _("Enabled") if updated_settings.not_on_online_enabled else _("Disabled")
        )
        await query.answer(
            _("NOON for subscriber {tg_id} set to: {status}.").format(
                tg_id=target_telegram_id, status=status
            )
        )
        await refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(_("Failed to toggle NOON status."), show_alert=True)


def _build_mute_list_title(
    translator: NullTranslations,
    user_settings: UserSettings,
    subscriber_display_name: str,
) -> str:
    """Builds the title for the mute list view."""
    _ = translator.gettext
    mode = (
        _("Blacklist")
        if user_settings.mute_list_mode == MuteListMode.blacklist
        else _("Whitelist")
    )
    return "\n".join(
        [
            _("Mute list for: {name} (ID: {id})").format(
                name=subscriber_display_name, id=user_settings.telegram_id
            ),
            _("Mute Mode: {mode}").format(mode=mode),
        ]
    )


@settings_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.ADMIN_VIEW_MUTE_LIST)
)
@ensure_message_context
async def admin_view_mute_list(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Entry point for an admin to view a specific subscriber's mute list."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    async with uow:
        view_data = await user_settings_service.get_subscriber_view_data(
            uow, target_telegram_id, translator.info().get("language", "en"), bot
        )
    if not view_data:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        return

    await _display_subscriber_mute_list_page(
        query=query,
        translator=translator,
        bot=bot,
        uow=uow,
        view_data=view_data,
        subscriber_list_return_page=callback_data.page,
        mute_list_page_num=0,
    )


async def _display_subscriber_mute_list_page(
    query: CallbackQuery,
    translator: NullTranslations,
    bot: EventBot,
    uow: IUnitOfWork,
    view_data: SubscriberViewData,
    subscriber_list_return_page: int,
    mute_list_page_num: int,
) -> None:
    """Displays a paginated view of a subscriber's mute list."""
    _ = translator.gettext
    user_settings = view_data.user_settings
    display_name = view_data.display_name
    target_telegram_id = user_settings.telegram_id

    if not query.bot:
        return

    full_mute_list = sorted(
        [mu.muted_teamtalk_username for mu in user_settings.muted_users_list]
    )
    # Inlining pagination logic to bypass a stubborn mypy error
    total_items = len(full_mute_list)
    page_size = MUTE_LIST_ITEMS_PER_PAGE
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    current_page_idx = max(0, min(mute_list_page_num, total_pages - 1))
    start_index = current_page_idx * page_size
    page_slice = full_mute_list[start_index : start_index + page_size]

    await display_paginated_list(
        target=query,
        bot=query.bot,
        translator=translator,
        items_on_page=page_slice,
        total_items=total_items,
        page=current_page_idx,
        title_text=_build_mute_list_title(translator, user_settings, display_name),
        empty_list_text=_("The mute list is currently empty."),
        keyboard_factory=create_view_mute_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_context_page": subscriber_list_return_page,
        },
        page_size=MUTE_LIST_ITEMS_PER_PAGE,
    )


@settings_router.callback_query(PaginateMuteListCallback.filter())
@ensure_message_context
async def paginate_mute_list(
    query: CallbackQuery,
    callback_data: PaginateMuteListCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Handles pagination for the admin's view of a subscriber's mute list."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        view_data = await user_settings_service.get_subscriber_view_data(
            uow, target_telegram_id, translator.info().get("language", "en"), bot
        )
        if not view_data:
            await query.answer(_("Subscriber settings not found."), show_alert=True)
            return

        await _display_subscriber_mute_list_page(
            query=query,
            translator=translator,
            bot=bot,
            uow=uow,
            view_data=view_data,
            subscriber_list_return_page=callback_data.subscriber_context_page,
            mute_list_page_num=callback_data.mute_list_page,
        )
    await query.answer()


AnySettingCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberMuteModeCallback
    | AdminSetSubscriberNotificationPrefCallback
)


@settings_router.callback_query(AdminSetSubscriberLanguageCallback.filter())
@ensure_message_context
async def admin_set_language(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberLanguageCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles an admin setting a subscriber's language."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        updated_settings = await user_settings_service.update_language(
            uow, target_telegram_id, callback_data.lang_code, Actor.ADMIN
        )
        await uow.commit()

    if updated_settings:
        success_msg = _("Language for subscriber {tg_id} changed to {value}.").format(
            tg_id=target_telegram_id, value=callback_data.lang_code
        )
        await query.answer(success_msg)
        await refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(
            _("Failed to update setting. Please try again."), show_alert=True
        )


@settings_router.callback_query(AdminSetSubscriberNotificationPrefCallback.filter())
@ensure_message_context
async def admin_set_notification_pref(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberNotificationPrefCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles an admin setting a subscriber's notification preference."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    new_pref = NotificationSetting(callback_data.setting_value)

    async with uow:
        updated_settings = await user_settings_service.update_notification_preference(
            uow, target_telegram_id, new_pref, Actor.ADMIN
        )
        await uow.commit()

    if updated_settings:
        success_msg = _(
            "Notification preference for subscriber {tg_id} set to: {value}."
        ).format(tg_id=target_telegram_id, value=new_pref.value)
        await query.answer(success_msg)
        await refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(
            _("Failed to update setting. Please try again."), show_alert=True
        )


@settings_router.callback_query(AdminSetSubscriberMuteModeCallback.filter())
@ensure_message_context
async def admin_set_mute_mode(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberMuteModeCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles an admin setting a subscriber's mute list mode."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id

    async with uow:
        updated_settings = await user_settings_service.update_mute_mode(
            uow, target_telegram_id, callback_data.mode, Actor.ADMIN
        )
        await uow.commit()

    if updated_settings:
        success_msg = _(
            "Mute list mode for subscriber {tg_id} set to: {value}."
        ).format(tg_id=target_telegram_id, value=callback_data.mode.value)
        await query.answer(success_msg)
        await refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(
            _("Failed to update setting. Please try again."), show_alert=True
        )
