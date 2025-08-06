"""Keyboards for user-facing settings menus."""

from gettext import GNUTranslations, NullTranslations
from typing import cast

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk

from bot.core.enums import (
    LanguageChoice,
    NotificationControl,
    SettingsNavAction,
    SubscriptionSetting,
    UserListAction,
)
from bot.core.languages import LanguageInfo
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.telegram_bot.callback_data import (
    LanguageCallback,
    NotificationCallback,
    PaginateUsersCallback,
    SetMuteModeCallback,
    SettingsCallback,
    SubscriptionCallback,
)

from .shared import (
    _build_user_toggle_keyboard,
    _create_back_button_text,
    _create_option_selection_keyboard,
)

ttstr = pytalk.instance.sdk.ttstr


async def create_main_settings_keyboard(
    translator: NullTranslations,
) -> InlineKeyboardBuilder:
    """Creates the main settings menu keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("Language"),
        callback_data=SettingsCallback(action=SettingsNavAction.LANGUAGE).pack(),
    )
    builder.button(
        text=_("Subscription Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.SUBSCRIPTIONS).pack(),
    )
    builder.button(
        text=_("Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack(),
    )
    builder.adjust(1)
    return builder


async def create_language_selection_keyboard(
    translator: NullTranslations,
    available_languages: list[LanguageInfo],
) -> InlineKeyboardMarkup:
    """Creates the language selection keyboard using the generic helper."""
    options = [(lang["code"], lang["native_name"]) for lang in available_languages]

    def lang_callback_factory(lang_code_value: str) -> LanguageCallback:
        return LanguageCallback(action=LanguageChoice.SET_LANG, lang_code=lang_code_value)

    back_button_cb_data = SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=None,
        callback_data_factory=lang_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key=_create_back_button_text(translator, "Settings"),
        buttons_per_row=1,
    )


async def create_subscription_settings_keyboard(
    translator: NullTranslations, current_setting: NotificationSetting
) -> InlineKeyboardMarkup:
    """Creates the subscription settings keyboard using the generic helper."""
    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", NotificationSetting.ALL.value),
        NotificationSetting.LEAVE_OFF: ("Join Only", NotificationSetting.LEAVE_OFF.value),
        NotificationSetting.JOIN_OFF: ("Leave Only", NotificationSetting.JOIN_OFF.value),
        NotificationSetting.NONE: ("None", NotificationSetting.NONE.value),
    }
    options = [(val_str, text_source) for _setting_enum, (text_source, val_str) in settings_map_source.items()]

    def sub_callback_factory(setting_value_str: str) -> SubscriptionCallback:
        return SubscriptionCallback(action=SubscriptionSetting.SET_SUB, setting_value=setting_value_str)

    back_button_cb_data = SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=current_setting.value,
        callback_data_factory=sub_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key=_create_back_button_text(translator, "Settings"),
        buttons_per_row=1,
    )


async def create_notification_settings_keyboard(
    translator: NullTranslations, user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_settings.not_on_online_enabled
    status_text = _("Enabled") if is_noon_enabled else _("Disabled")
    noon_button_text = _("NOON (Not on Online): {status}").format(status=status_text)

    builder.button(
        text=noon_button_text,
        callback_data=NotificationCallback(action=NotificationControl.TOGGLE_NOON).pack(),
    )
    builder.button(
        text=_("Manage Mute List"),
        callback_data=NotificationCallback(action=NotificationControl.MANAGE_MUTED).pack(),
    )
    builder.button(
        text=_create_back_button_text(translator, "Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack(),
    )
    builder.adjust(1)
    return builder


async def create_manage_muted_users_keyboard(
    translator: NullTranslations, user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the 'Manage Mute List' keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    active_marker = "✅"
    inactive_marker = "⚪️"

    blacklist_marker = active_marker if user_settings.mute_list_mode == MuteListMode.blacklist else inactive_marker
    whitelist_marker = active_marker if user_settings.mute_list_mode == MuteListMode.whitelist else inactive_marker

    blacklist_text = _("{marker} Blacklist Mode").format(marker=blacklist_marker)
    whitelist_text = _("{marker} Whitelist Mode").format(marker=whitelist_marker)

    builder.button(
        text=blacklist_text,
        callback_data=SetMuteModeCallback(mode=MuteListMode.blacklist).pack(),
    )
    builder.button(
        text=whitelist_text,
        callback_data=SetMuteModeCallback(mode=MuteListMode.whitelist).pack(),
    )
    builder.adjust(2)

    if user_settings.mute_list_mode == MuteListMode.blacklist:
        list_mode_text = _("Manage Blacklist")
    else:
        list_mode_text = _("Manage Whitelist")
    builder.button(
        text=list_mode_text,
        callback_data=PaginateUsersCallback(list_type=UserListAction.LIST_MUTED, page=0).pack(),
    )

    builder.button(
        text=_("Mute/Unmute from Server List"),
        callback_data=PaginateUsersCallback(list_type=UserListAction.LIST_ALL_ACCOUNTS, page=0).pack(),
    )
    builder.button(
        text=_create_back_button_text(translator, "Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack(),
    )
    builder.adjust(1)
    return builder


async def create_paginated_user_list_keyboard(
    translator: NullTranslations,
    page_items: list[str],
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    user_settings: UserSettings,
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""

    def username_extractor(item: str) -> str:
        return item

    def display_name_extractor(item: str) -> str:
        return item

    return await _build_user_toggle_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=list_type,
        item_username_extractor=username_extractor,
        item_display_name_extractor=display_name_extractor,
        back_button_callback_data=NotificationCallback(action=NotificationControl.MANAGE_MUTED).pack(),
        back_button_text_key=_create_back_button_text(translator, "Mute Management"),
    )


async def create_account_list_keyboard(
    translator: NullTranslations,
    page_items: list[pytalk.UserAccount],
    current_page: int,
    total_pages: int,
    user_settings: UserSettings,
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of all server user accounts."""

    def username_extractor(item: pytalk.UserAccount) -> str:
        return cast(str, ttstr(item.username))

    def display_name_extractor(item: pytalk.UserAccount) -> str:
        return cast(str, ttstr(item.username))

    return await _build_user_toggle_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=UserListAction.LIST_ALL_ACCOUNTS,
        item_username_extractor=username_extractor,
        item_display_name_extractor=display_name_extractor,
        back_button_callback_data=NotificationCallback(action=NotificationControl.MANAGE_MUTED).pack(),
        back_button_text_key=_create_back_button_text(translator, "Mute Management"),
    )
