"""Keyboards for user-facing settings menus."""

from gettext import NullTranslations

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
from bot.models import MuteListMode, NotificationSetting
from bot.services.schemas import SettingsViewDTO
from bot.telegram_bot.callback_data import (
    LanguageCallback,
    NotificationCallback,
    PaginateUsersCallback,
    SetMuteModeCallback,
    SettingsCallback,
    SubscriptionCallback,
)

from .keyboard_utils import (
    get_language_options,
    get_notification_settings_options,
)
from .shared import (
    _create_option_selection_keyboard,
    add_back_button,
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
    _ = translator.gettext
    options = get_language_options(available_languages)

    def lang_callback_factory(lang_code_value: str) -> LanguageCallback:
        return LanguageCallback(
            action=LanguageChoice.SET_LANG, lang_code=lang_code_value
        )

    back_button_cb_data = SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=None,
        callback_data_factory=lang_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key=_("Settings"),
        buttons_per_row=1,
    )


async def create_subscription_settings_keyboard(
    translator: NullTranslations, current_setting: NotificationSetting
) -> InlineKeyboardMarkup:
    """Creates the subscription settings keyboard using the generic helper."""
    _ = translator.gettext
    options = get_notification_settings_options()

    def sub_callback_factory(setting_value_str: str) -> SubscriptionCallback:
        return SubscriptionCallback(
            action=SubscriptionSetting.SET_SUB, setting_value=setting_value_str
        )

    back_button_cb_data = SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN)

    return await _create_option_selection_keyboard(
        translator=translator,
        options=options,
        current_value=current_setting.value,
        callback_data_factory=sub_callback_factory,
        back_button_callback_data=back_button_cb_data,
        back_button_text_key=_("Settings"),
        buttons_per_row=1,
    )


async def create_notification_settings_keyboard(
    translator: NullTranslations, user_settings: SettingsViewDTO
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_settings.not_on_online_enabled
    status_text = _("Enabled") if is_noon_enabled else _("Disabled")
    noon_button_text = _("NOON (Not on Online): {status}").format(status=status_text)

    builder.button(
        text=noon_button_text,
        callback_data=NotificationCallback(
            action=NotificationControl.TOGGLE_NOON
        ).pack(),
    )
    builder.button(
        text=_("Manage Mute List"),
        callback_data=NotificationCallback(
            action=NotificationControl.MANAGE_MUTED
        ).pack(),
    )
    add_back_button(
        builder,
        translator,
        _("Settings"),
        SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN),
    )
    builder.adjust(1)
    return builder


async def create_manage_muted_users_keyboard(
    translator: NullTranslations, user_settings: SettingsViewDTO
) -> InlineKeyboardBuilder:
    """Creates the 'Manage Mute List' keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    active_marker = "✅"
    inactive_marker = "⚪️"

    blacklist_marker = (
        active_marker
        if user_settings.mute_list_mode == MuteListMode.blacklist
        else inactive_marker
    )
    whitelist_marker = (
        active_marker
        if user_settings.mute_list_mode == MuteListMode.whitelist
        else inactive_marker
    )

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
        callback_data=PaginateUsersCallback(
            list_type=UserListAction.LIST_MUTED, page=0
        ).pack(),
    )

    builder.button(
        text=_("Mute/Unmute from Server List"),
        callback_data=PaginateUsersCallback(
            list_type=UserListAction.LIST_ALL_ACCOUNTS, page=0
        ).pack(),
    )
    add_back_button(
        builder,
        translator,
        _("Notification Settings"),
        SettingsCallback(action=SettingsNavAction.NOTIFICATIONS),
    )
    builder.adjust(1)
    return builder
