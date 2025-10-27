"""Callback query handlers for core actions related to specific subscribers."""

from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Annotated, Any, TypeAlias, TypedDict, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.commands import GetAllTeamTalkAccountsCommand, GetAllTeamTalkAccountsResult
from bot.constants import MUTE_LIST_ITEMS_PER_PAGE, USERS_PER_PAGE
from bot.core.enums import (
    Actor,
    ManageTTAccountAction,
    SubscriberCommand,
    SubscriberListAction,
)
from bot.core.languages import LanguageInfo
from bot.database.models import UserSettings
from bot.database.types import MuteListMode, NotificationSetting
from bot.database.uow import IUnitOfWork
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO, SubscriberView
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    PaginateLinkableAccountsCallback,
    PaginateMuteListCallback,
    SubscriberCallback,
    SubscriberListCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.formatters import format_subscriber_details
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import (
    create_admin_subscriber_lang_keyboard,
    create_admin_subscriber_mute_mode_keyboard,
    create_admin_subscriber_notification_pref_keyboard,
    create_linkable_tt_account_list_keyboard,
    create_manage_tt_account_keyboard,
    create_subscriber_action_menu_keyboard,
    create_view_mute_list_keyboard,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import (
    display_paginated_list,
    edit_message_text,
    refresh_subscriber_list_view,
)
from bot.utils.pagination import paginate_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from bot.services.schemas import UserAccountInfo


logger = logging.getLogger(__name__)
subscriber_details_router = Router(name="subscriber_details_router")


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    view_data: SubscriberView,
    translator: NullTranslations,
) -> None:
    """Helper function to display the subscriber details view."""
    keyboard = create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    # The user_settings object is now nested inside the view_data DTO
    user_settings_dto = SettingsViewDTO(
        telegram_id=view_data.user_settings.telegram_id,
        language_code=view_data.user_settings.language_code,
        notification_settings=view_data.user_settings.notification_settings,
        mute_list_mode=view_data.user_settings.mute_list_mode,
        not_on_online_enabled=view_data.user_settings.not_on_online_enabled,
        not_on_online_confirmed=view_data.user_settings.not_on_online_confirmed,
        teamtalk_username=view_data.user_settings.teamtalk_username,
        muted_users_count=len(view_data.user_settings.muted_users_list),
    )
    text = format_subscriber_details(
        user_settings_dto, view_data.display_name, translator
    )

    # This assumes query.message is a Message, which is guaranteed by
    # @ensure_message_context
    await cast("Message", query.message).edit_text(
        text, reply_markup=keyboard, parse_mode="HTML"
    )


async def _refresh_subscriber_view(
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
    async with uow:
        view_data = await user_settings_service.get_subscriber_view_data(
            uow,
            target_telegram_id,
            "en",  # lang doesn\'t matter here
            bot,
        )
    if not view_data:
        logger.error(
            "_refresh_subscriber_view could not fetch view_data for TG ID %s",
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


@subscriber_details_router.callback_query(
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

    async with uow:
        result = await subscription_service.delete_profile(
            uow, target_telegram_id, translator
        )
        await uow.commit()

    message = result.message_key.format(
        **(cast("dict[str, Any]", result.message_args) or {})
    )
    await query.answer(message, show_alert=True)

    if result.success:
        await refresh_subscriber_list_view(
            query,
            callback_data,
            translator,
            bot,
            report_service=report_service,
            uow=uow,
        )


@subscriber_details_router.callback_query(
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

    short_message = _(result.message_key).format(
        **(cast("dict[str, Any]", result.message_args) or {})
    )

    await query.answer(short_message, show_alert=True)

    if result.success:
        await refresh_subscriber_list_view(
            query,
            callback_data,
            translator,
            bot,
            report_service=report_service,
            uow=uow,
        )


@subscriber_details_router.callback_query(
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
    target_telegram_id = callback_data.target_telegram_id
    async with uow:
        result = await subscription_service.delete_profile(
            uow, target_telegram_id, translator
        )
        await uow.commit()

    message = result.message_key.format(
        **(cast("dict[str, Any]", result.message_args) or {})
    )
    await query.answer(message, show_alert=True)

    if result.success:
        await refresh_subscriber_list_view(
            query,
            callback_data,
            translator,
            bot,
            report_service=report_service,
            uow=uow,
        )


@subscriber_details_router.callback_query(ViewSubscriberCallback.filter())
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
            "en",  # lang doesn\'t matter here
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


class SettingChoiceConfig(TypedDict):
    """A type hint for the setting choice configuration dictionary."""

    message_text: str
    keyboard_factory: "Callable[..., InlineKeyboardMarkup]"
    keyboard_factory_kwargs: dict[str, object]


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


@subscriber_details_router.callback_query(
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


@subscriber_details_router.callback_query(
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
        await _refresh_subscriber_view(
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


@subscriber_details_router.callback_query(
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
    r"""Entry point for an admin to view a specific subscriber\'s mute list."""
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
    view_data: SubscriberView,
    subscriber_list_return_page: int,
    mute_list_page_num: int,
) -> None:
    r"""Displays a paginated view of a subscriber\'s mute list."""
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


@subscriber_details_router.callback_query(PaginateMuteListCallback.filter())
@ensure_message_context
async def paginate_mute_list(
    query: CallbackQuery,
    callback_data: PaginateMuteListCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    r"""Handles pagination for the admin\'s view of a subscriber\'s mute list."""
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


AnySettingCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberMuteModeCallback
    | AdminSetSubscriberNotificationPrefCallback
)


@subscriber_details_router.callback_query(AdminSetSubscriberLanguageCallback.filter())
@ensure_message_context
async def admin_set_language(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberLanguageCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    r"""Handles an admin setting a subscriber\'s language."""
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
        await _refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )


@subscriber_details_router.callback_query(
    AdminSetSubscriberNotificationPrefCallback.filter()
)
@ensure_message_context
async def admin_set_notification_pref(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberNotificationPrefCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    r"""Handles an admin setting a subscriber\'s notification preference."""
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
        await _refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )


@subscriber_details_router.callback_query(AdminSetSubscriberMuteModeCallback.filter())
@ensure_message_context
async def admin_set_mute_mode(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberMuteModeCallback,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_settings_service: FromDishka[UserSettingsService],
    uow: FromDishka[IUnitOfWork],
) -> None:
    r"""Handles an admin setting a subscriber\'s mute list mode."""
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
        await _refresh_subscriber_view(
            query,
            callback_data,
            translator,
            bot,
            user_settings_service=user_settings_service,
            uow=uow,
        )
    else:
        await query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )


@subscriber_details_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.MANAGE_TT_ACCOUNT)
)
@ensure_message_context
async def manage_tt_account(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    r"""Shows the menu to manage a subscriber\'s linked TeamTalk account."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    async with uow:
        data = await user_settings_service.get_account_management_data(
            uow, target_telegram_id
        )

    keyboard = create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=data.current_tt_username,
        page=return_page,
    )
    message_text = _(
        "Manage TeamTalk account link for subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)

    await edit_message_text(
        message_to_edit=cast("Message", query.message),
        text=message_text,
        reply_markup=keyboard,
    )


@subscriber_details_router.callback_query(
    ManageTTAccountCallback.filter(F.action == ManageTTAccountAction.LINK_NEW)
)
@ensure_message_context
async def link_new_tt_account_choice(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    translator: FromDishka[NullTranslations],
    command_bus: Annotated[CommandBus, FromDishka()],
) -> None:
    """Handle 'Link/Change TeamTalk Account' action by showing linkable accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.page,
        linkable_accounts_page_to_show=0,
        command_bus=command_bus,
        translator=translator,
    )


async def _display_linkable_tt_accounts_page(
    query: CallbackQuery,
    target_telegram_id: int,
    subscriber_context_page: int,
    linkable_accounts_page_to_show: int,
    command_bus: CommandBus,
    translator: NullTranslations,
) -> None:
    """Helper to display a paginated list of linkable TeamTalk accounts."""
    _ = translator.gettext

    result: GetAllTeamTalkAccountsResult = await command_bus.execute(
        GetAllTeamTalkAccountsCommand(lang_code=translator.info().get("language", "en"))
    )

    if not result.success:
        logger.warning(
            "Failed to get TeamTalk accounts for linking. User %s. Error: %s",
            query.from_user.id,
            result.error_message,
        )
        await query.answer(result.error_message, show_alert=True)
        return

    all_server_accounts: list[UserAccountInfo] = result.accounts

    try:
        all_server_accounts.sort(key=lambda acc: acc.username.lower())
    except TypeError:
        logger.exception(
            "Error sorting server accounts for user %s. Proceeding with unsorted list.",
            query.from_user.id,
        )

    title_text = _(
        "Select a TeamTalk account to link to subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)
    empty_list_text = _("No TeamTalk server accounts found.")

    if not all_server_accounts:
        empty_list_text = _("No TeamTalk server accounts found or unable to fetch.")

    if query.bot is None:
        logger.error(
            "_display_linkable_tt_accounts_page: query.bot is None. "
            "Cannot display list."
        )
        await query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    page_slice, _, current_page_idx = paginate_list(
        all_server_accounts, linkable_accounts_page_to_show, USERS_PER_PAGE
    )

    await display_paginated_list(
        target=query,
        bot=query.bot,
        translator=translator,
        items_on_page=page_slice,
        total_items=len(all_server_accounts),
        page=current_page_idx,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_linkable_tt_account_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_list_page": subscriber_context_page,
        },
        page_size=USERS_PER_PAGE,
        server_host_for_display=None,
    )


@subscriber_details_router.callback_query(PaginateLinkableAccountsCallback.filter())
@ensure_message_context
async def paginate_linkable_accounts(
    query: CallbackQuery,
    callback_data: PaginateLinkableAccountsCallback,
    command_bus: Annotated[CommandBus, FromDishka()],
    translator: FromDishka[NullTranslations],
) -> None:
    """Handles pagination for the list of linkable TeamTalk accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.subscriber_context_page,
        linkable_accounts_page_to_show=callback_data.page,
        command_bus=command_bus,
        translator=translator,
    )


@subscriber_details_router.callback_query(LinkTTAccountChosenCallback.filter())
@ensure_message_context
async def link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    subscription_service: FromDishka[SubscriptionService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles the selection of a TeamTalk account to link to a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    tt_username = callback_data.tt_username
    return_page = callback_data.page

    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow,
            target_telegram_id,
            "en",  # Language doesn\'t matter for this operation
        )
        if not user_settings:
            await query.answer(_("Subscriber settings not found."), show_alert=True)
            return

        result = await subscription_service.link_tt_account(
            uow, user_settings, tt_username, translator
        )
        await uow.commit()

    toast_message = _(result.message_key).format(
        **(cast("dict[str, Any]", result.message_args) or {})
    )
    await query.answer(toast_message, show_alert=not result.success)

    if result.success:
        # Refresh the manage TT account view
        keyboard = create_manage_tt_account_keyboard(
            translator,
            target_telegram_id=target_telegram_id,
            current_tt_username=tt_username,
            page=return_page,
        )
        message_text = _(
            "Manage TeamTalk account link for subscriber {telegram_id}:"
        ).format(telegram_id=target_telegram_id)
        if not query.message:
            logger.error("CallbackQuery message is None in link_tt_account_chosen.")
            await query.answer(
                _("An error occurred. Please try again later."), show_alert=True
            )
            return

        await edit_message_text(
            message_to_edit=query.message,
            text=message_text,
            reply_markup=keyboard,
        )


@subscriber_details_router.callback_query(
    ManageTTAccountCallback.filter(F.action == ManageTTAccountAction.UNLINK)
)
@ensure_message_context
async def unlink_tt_account(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles unlinking a TeamTalk account from a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    async with uow:
        (
            updated_settings,
            original_username,
        ) = await user_settings_service.unlink_tt_account(
            uow, target_telegram_id, actor=Actor.ADMIN
        )
        await uow.commit()

    if not updated_settings:
        await query.answer(
            _("Failed to unlink account. Please try again."), show_alert=True
        )
        return

    if original_username is None:
        await query.answer(_("Account was not linked."), show_alert=False)
        return

    toast_message = _("Account {username} has been unlinked.").format(
        username=original_username
    )
    await query.answer(toast_message, show_alert=True)

    keyboard = create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=None,  # The account is now unlinked
        page=return_page,
    )
    message_text = _(
        "Manage TeamTalk account link for subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)
    if not query.message:
        logger.error("CallbackQuery message is None in unlink_tt_account.")
        await query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return
    await edit_message_text(
        message_to_edit=query.message,
        text=message_text,
        reply_markup=keyboard,
    )
