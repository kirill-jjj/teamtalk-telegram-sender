"""Keyboard utilities for the Telegram bot.

This module provides functions to generate and manage custom keyboards
for Telegram interactions using InlineKeyboardBuilder.
"""

import gettext
import html
from typing import TYPE_CHECKING, Any, cast  # Added TYPE_CHECKING, Type and cast, removed Type

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Removed unused import: from collections.abc import Callable
from aiogram.utils.keyboard import InlineKeyboardBuilder
import pytalk  # For UserAccount type hint

from bot.core.enums import (
    AdminAction,
    LanguageAction,
    ManageTTAccountAction,
    NotificationAction,
    SettingsNavAction,
    SubscriberAction,
    SubscriberListAction,
    SubscriptionAction,
    ToggleMuteSpecificAction,
    UserListAction,
)
from bot.core.languages import LanguageInfo  # Added
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.teamtalk_bot.utils import get_tt_user_display_name  # Updated import
from bot.telegram_bot.callback_data import (
    AdminActionCallback,
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,  # Added
    AdminSetSubscriberNotificationPrefCallback,
    LanguageCallback,
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    MenuCallback,
    NotificationActionCallback,
    PaginateLinkableAccountsCallback,
    PaginateMuteListCallback,  # New
    PaginateUsersCallback,
    SetMuteModeCallback,
    SettingsCallback,
    SubscriberActionCallback,
    SubscriberListCallback,
    SubscriptionCallback,
    ToggleMuteSpecificCallback,
    UserListCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.models import SubscriberInfo

if TYPE_CHECKING:
    from collections.abc import Callable  # Moved here

ttstr = pytalk.instance.sdk.ttstr


# --- Helper Functions ---


def _is_username_effectively_muted(username: str, user_settings: UserSettings, muted_usernames_set: set[str]) -> bool:
    """Determines if a username is effectively muted based on user settings.

    - If `user_settings.mute_list_mode` is `MuteListMode.whitelist`, the
      `muted_usernames_set` is treated as an allow list; the user is considered
      muted if their username is NOT in this set.
    - If `user_settings.mute_list_mode` is `MuteListMode.blacklist`, the
      `muted_usernames_set` is treated as a block list; the user is considered
      muted if their username IS in this set.

    Args:
        username: The TeamTalk username to check.
        user_settings: The UserSettings object for the Telegram user.
        muted_usernames_set: A set of TeamTalk usernames, acting as either an
                             allow list or a block list based on `user_settings.mute_list_mode`.

    Returns:
        True if the user is effectively muted, False otherwise.
    """
    is_in_set = username in muted_usernames_set
    if user_settings.mute_list_mode == MuteListMode.whitelist:
        return not is_in_set  # Muted if not in the allow list
    # blacklist mode
    return is_in_set  # Muted if in the block list


# --- Settings Keyboards ---


async def create_main_settings_keyboard(
    translator: gettext.GNUTranslations | gettext.NullTranslations,
) -> InlineKeyboardBuilder:
    """Creates the main settings menu keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    builder.button(text=_("Language"), callback_data=SettingsCallback(action=SettingsNavAction.LANGUAGE).pack())
    builder.button(
        text=_("Subscription Settings"), callback_data=SettingsCallback(action=SettingsNavAction.SUBSCRIPTIONS).pack()
    )
    builder.button(
        text=_("Notification Settings"), callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack()
    )
    builder.adjust(1)
    return builder


async def create_language_selection_keyboard(
    translator: gettext.GNUTranslations, available_languages: list[LanguageInfo]
) -> InlineKeyboardBuilder:
    """Creates the language selection keyboard dynamically."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    if not available_languages:
        builder.button(text="No languages available", callback_data="noop")
    else:
        for lang_info in available_languages:
            builder.button(
                text=lang_info["native_name"],
                callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code=lang_info["code"]).pack(),
            )

    builder.button(
        text=_("⬅️ Back to Settings"), callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder


async def create_subscription_settings_keyboard(
    translator: gettext.GNUTranslations, current_setting: NotificationSetting
) -> InlineKeyboardBuilder:
    """Creates the subscription settings keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", "all"),
        NotificationSetting.LEAVE_OFF: ("Join Only", "leave_off"),
        NotificationSetting.JOIN_OFF: ("Leave Only", "join_off"),
        NotificationSetting.NONE: ("None", "none"),
    }

    for setting_enum, (text_source, val_str) in settings_map_source.items():
        button_text = _("✅ {text}").format(text=_(text_source)) if current_setting == setting_enum else _(text_source)

        builder.button(
            text=button_text,
            callback_data=SubscriptionCallback(action=SubscriptionAction.SET_SUB, setting_value=val_str).pack(),
        )

    builder.button(
        text=_("⬅️ Back to Settings"), callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder


async def create_notification_settings_keyboard(
    translator: gettext.GNUTranslations, user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_settings.not_on_online_enabled
    status_text = _("Enabled") if is_noon_enabled else _("Disabled")
    noon_button_text = _("NOON (Not on Online): {status}").format(status=status_text)

    builder.button(
        text=noon_button_text, callback_data=NotificationActionCallback(action=NotificationAction.TOGGLE_NOON).pack()
    )
    builder.button(
        text=_("Manage Mute List"),
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack(),
    )
    builder.button(
        text=_("⬅️ Back to Settings"), callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder


async def create_manage_muted_users_keyboard(
    translator: gettext.GNUTranslations, user_settings: UserSettings
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

    builder.button(text=blacklist_text, callback_data=SetMuteModeCallback(mode=MuteListMode.blacklist).pack())
    builder.button(text=whitelist_text, callback_data=SetMuteModeCallback(mode=MuteListMode.whitelist).pack())
    builder.adjust(2)

    if user_settings.mute_list_mode == MuteListMode.blacklist:
        list_mode_text = _("Manage Blacklist")
    else:
        list_mode_text = _("Manage Whitelist")
    builder.button(text=list_mode_text, callback_data=UserListCallback(action=UserListAction.LIST_MUTED).pack())

    builder.button(
        text=_("Mute/Unmute from Server List"),
        callback_data=UserListCallback(action=UserListAction.LIST_ALL_ACCOUNTS).pack(),
    )
    builder.button(
        text=_("⬅️ Back to Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack(),
    )
    builder.adjust(1)
    return builder


# --- Paginated List Keyboards ---


async def _add_pagination_controls(
    builder: InlineKeyboardBuilder,
    translator: gettext.GNUTranslations,
    current_page: int,
    total_pages: int,
    list_type: UserListAction,  # This argument might become part of a more generic callback_factory signature
    callback_factory: type[PaginateUsersCallback],  # Changed to type[PaginateUsersCallback]
) -> None:
    """Adds pagination controls (Previous/Next) to the keyboard builder."""
    _ = translator.gettext
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"), callback_data=callback_factory(list_type=list_type, page=current_page - 1).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"), callback_data=callback_factory(list_type=list_type, page=current_page + 1).pack()
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


async def create_paginated_user_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[str],
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    user_settings: UserSettings,
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""
    _ = translator.gettext

    def username_extractor(item: str) -> str:
        return item

    def display_name_extractor(item: str) -> str:
        return item

    return await _create_generic_user_toggle_list_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=list_type,
        item_username_extractor=username_extractor,
        item_display_name_extractor=display_name_extractor,
        back_button_callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack(),
        back_button_text_key="⬅️ Back to Mute Management",
    )


async def create_account_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[pytalk.UserAccount],
    current_page: int,
    total_pages: int,
    user_settings: UserSettings,
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of all server user accounts."""
    _ = translator.gettext

    def username_extractor(item: pytalk.UserAccount) -> str:
        return cast(str, ttstr(item.username))

    def display_name_extractor(item: pytalk.UserAccount) -> str:
        return cast(str, ttstr(item.username))

    return await _create_generic_user_toggle_list_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=UserListAction.LIST_ALL_ACCOUNTS,
        item_username_extractor=username_extractor,
        item_display_name_extractor=display_name_extractor,
        back_button_callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack(),
        back_button_text_key="⬅️ Back to Mute Management",
    )


# --- START NEW GENERIC PAGINATION HELPERS ---


def _add_pagination_controls_generic(
    builder: InlineKeyboardBuilder,
    translator: gettext.GNUTranslations,
    current_page: int,
    total_pages: int,
    pagination_callback_factory: "Callable[..., Any]",
    # To pass additional fixed args to the pagination_callback_factory
    **factory_kwargs: Any,  # noqa: ANN401
) -> None:
    """Adds generic pagination controls (Previous/Next) to the keyboard builder."""
    _ = translator.gettext
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=pagination_callback_factory(page=current_page - 1, **factory_kwargs).pack(),
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=pagination_callback_factory(page=current_page + 1, **factory_kwargs).pack(),
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


async def _create_generic_paginated_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[Any],
    current_page: int,
    total_pages: int,
    item_button_former: "Callable[[Any, int, Callable[[str], str]], InlineKeyboardButton | list[InlineKeyboardButton]]",
    pagination_callback_factory: "Callable[..., Any]",
    pagination_factory_kwargs: dict[str, Any] | None = None,  # For additional fixed args to pagination_callback_factory
    additional_buttons_top: list[list[InlineKeyboardButton]] | None = None,
    additional_buttons_bottom: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    """Generic helper to create a keyboard for a paginated list of items.

    item_button_former should be a synchronous function.
    """
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    if additional_buttons_top:
        for row_buttons in additional_buttons_top:
            builder.row(*row_buttons)

    for item in page_items:
        button_or_buttons = item_button_former(item, current_page, _)  # Pass _ directly

        if isinstance(button_or_buttons, list):
            builder.row(*button_or_buttons)
        else:
            builder.row(button_or_buttons)

    if total_pages > 1:
        factory_kwargs_to_pass = pagination_factory_kwargs if pagination_factory_kwargs is not None else {}
        _add_pagination_controls_generic(
            builder, translator, current_page, total_pages, pagination_callback_factory, **factory_kwargs_to_pass
        )

    if additional_buttons_bottom:
        for row_buttons in additional_buttons_bottom:
            builder.row(*row_buttons)

    return builder.as_markup()


# --- END NEW GENERIC PAGINATION HELPERS ---


async def create_subscriber_list_keyboard(
    translator: gettext.GNUTranslations,
    page_subscribers_info: list[SubscriberInfo],
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the subscriber list using the generic helper."""
    _ = translator.gettext

    def subscriber_button_former(
        subscriber: SubscriberInfo, page_num: int, _translate: "Callable[[str], str]"
    ) -> InlineKeyboardButton:
        user_info_parts = [subscriber.display_name]
        if subscriber.teamtalk_username:
            user_info_parts.append(f"TT: {html.escape(subscriber.teamtalk_username)}")
        button_text = ", ".join(user_info_parts)

        return InlineKeyboardButton(
            text=button_text,
            callback_data=ViewSubscriberCallback(telegram_id=subscriber.telegram_id, page=page_num).pack(),
        )

    pagination_kwargs = {"action": SubscriberListAction.PAGE}

    return await _create_generic_paginated_list_keyboard(
        translator=translator,
        page_items=page_subscribers_info,
        current_page=current_page,
        total_pages=total_pages,
        item_button_former=subscriber_button_former,
        pagination_callback_factory=SubscriberListCallback,  # Pass the class directly
        pagination_factory_kwargs=pagination_kwargs,
    )


async def create_user_selection_keyboard(
    translator: gettext.GNUTranslations, users_to_display: list[pytalk.user.User], command_type: AdminAction
) -> InlineKeyboardBuilder:
    """Creates a keyboard with buttons for each user in the provided list."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    for user_obj in users_to_display:
        if not user_obj:
            continue
        user_nickname = get_tt_user_display_name(user_obj, translator)
        if not hasattr(user_obj, "id"):
            continue
        user_id = user_obj.id
        callback_data = AdminActionCallback(action=command_type, user_id=user_id).pack()
        builder.button(text=html.escape(user_nickname), callback_data=callback_data)
    builder.adjust(2)
    return builder


async def create_main_menu_keyboard(translator: gettext.GNUTranslations, *, is_admin: bool) -> InlineKeyboardBuilder:
    """Creates the main menu keyboard with commands."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    builder.button(text=_("ℹ️ Who is online?"), callback_data=MenuCallback(command="who").pack())
    builder.button(text=_("⚙️ Settings"), callback_data=MenuCallback(command="settings").pack())
    builder.button(text=_("❓ Help"), callback_data=MenuCallback(command="help").pack())
    if is_admin:
        builder.button(text=_("👢 Kick User"), callback_data=MenuCallback(command="kick").pack())
        builder.button(text=_("🚫 Ban User"), callback_data=MenuCallback(command="ban").pack())
        builder.button(text=_("👥 Subscribers"), callback_data=MenuCallback(command="subscribers").pack())
    builder.adjust(1)
    return builder


async def create_subscriber_action_menu_keyboard(
    translator: gettext.GNUTranslations, target_telegram_id: int, page: int
) -> InlineKeyboardMarkup:
    """Creates the action menu for a specific subscriber."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("🗑️ Delete Subscriber"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.DELETE, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("🚫 Ban User (TG & TT)"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.BAN, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("🔗 Manage TeamTalk Account"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.MANAGE_TT_ACCOUNT, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    # New admin settings modification buttons
    builder.button(
        text=_("🗣️ Change Language"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_SET_LANGUAGE, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("🌞 Toggle NOON"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_TOGGLE_NOON, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("🔔 Set Notification Prefs"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_SET_NOTIF_PREF, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("🔇 Set Mute Mode"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_SET_MUTE_MODE, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("📜 View Mute List"),  # Placeholder text, might need refinement
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.ADMIN_VIEW_MUTE_LIST, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("⬅️ Back to Subscribers List"),
        callback_data=SubscriberListCallback(action=SubscriberListAction.PAGE, page=page).pack(),
    )
    builder.adjust(1)  # Adjust to 1 column for settings, then back button
    return builder.as_markup()


# --- Generic Helper for Paginated User Lists with Toggle ---
async def _create_generic_user_toggle_list_keyboard(
    translator: gettext.GNUTranslations,
    page_items: list[Any],
    current_page: int,
    total_pages: int,
    user_settings: UserSettings,
    list_type_for_callback: UserListAction,
    item_username_extractor: "Callable[[Any], str]",
    item_display_name_extractor: "Callable[[Any], str]",
    back_button_callback_data: str,
    back_button_text_key: str,
) -> InlineKeyboardMarkup:
    """Generic helper to create a keyboard for a paginated list of users.

    Includes mute/unmute toggle buttons.
    """
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    muted_usernames_from_relationship = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}

    for idx, item in enumerate(page_items):
        username_str = item_username_extractor(item)
        display_name_on_button = item_display_name_extractor(item)
        effectively_muted = _is_username_effectively_muted(
            username_str, user_settings, muted_usernames_from_relationship
        )
        if effectively_muted:
            button_text = _("{item_display_name} (Status: Muted)").format(
                item_display_name=html.escape(display_name_on_button)
            )
        else:
            button_text = _("{item_display_name} (Status: Not Muted)").format(
                item_display_name=html.escape(display_name_on_button)
            )
        callback_d = ToggleMuteSpecificCallback(
            action=ToggleMuteSpecificAction.TOGGLE_USER,
            user_idx=idx,
            current_page=current_page,
            list_type=list_type_for_callback,
        ).pack()
        builder.button(text=button_text, callback_data=callback_d)

    if page_items:
        builder.adjust(1)

    await _add_pagination_controls(
        builder, translator, current_page, total_pages, list_type_for_callback, PaginateUsersCallback
    )

    builder.row(InlineKeyboardButton(text=_(back_button_text_key), callback_data=back_button_callback_data))
    return builder.as_markup()


async def create_manage_tt_account_keyboard(
    translator: gettext.GNUTranslations,
    target_telegram_id: int,
    current_tt_username: str | None,
    page: int,
    _list_action_page: int = 0,
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing a subscriber's TeamTalk account link."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    if current_tt_username:
        builder.button(
            text=_("➖ Unlink {current_tt_username}").format(current_tt_username=html.escape(current_tt_username)),
            callback_data=ManageTTAccountCallback(
                action=ManageTTAccountAction.UNLINK, target_telegram_id=target_telegram_id, page=page
            ).pack(),
        )

    builder.button(
        text=_("➕ Link/Change TeamTalk Account"),
        callback_data=ManageTTAccountCallback(
            action=ManageTTAccountAction.LINK_NEW, target_telegram_id=target_telegram_id, page=page
        ).pack(),
    )
    builder.button(
        text=_("⬅️ Back to User Actions"),
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=page).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


async def create_view_mute_list_keyboard(
    translator: gettext.GNUTranslations,
    current_mute_list_page: int,
    total_mute_list_pages: int,
    target_telegram_id: int,  # Subscriber's ID
    subscriber_context_page: int,  # Page of the main subscriber list (for back button)
) -> InlineKeyboardMarkup:
    """Creates the keyboard for viewing a paginated mute list for a specific subscriber."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    pagination_buttons = []
    if current_mute_list_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev Page"),  # Text for mute list page
                callback_data=PaginateMuteListCallback(
                    target_telegram_id=target_telegram_id,
                    mute_list_page=current_mute_list_page - 1,
                    subscriber_context_page=subscriber_context_page,
                ).pack(),
            )
        )
    if current_mute_list_page < total_mute_list_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next Page ➡️"),  # Text for mute list page
                callback_data=PaginateMuteListCallback(
                    target_telegram_id=target_telegram_id,
                    mute_list_page=current_mute_list_page + 1,
                    subscriber_context_page=subscriber_context_page,
                ).pack(),
            )
        )

    if pagination_buttons:
        builder.row(*pagination_buttons)

    # Button to go back to the specific subscriber's action menu
    builder.row(
        InlineKeyboardButton(
            text=_("⬅️ Back to User Actions"),  # This text should already be translated
            callback_data=ViewSubscriberCallback(
                telegram_id=target_telegram_id,
                page=subscriber_context_page,  # This page is for the main subscriber list
            ).pack(),
        )
    )
    return builder.as_markup()


async def create_admin_subscriber_mute_mode_keyboard(
    translator: gettext.GNUTranslations,
    current_mode: MuteListMode,  # Subscriber's current mute mode
    target_telegram_id: int,
    subscriber_page_context: int,
) -> InlineKeyboardMarkup:
    """Creates the mute mode selection keyboard for an admin to change for a subscriber."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()
    active_marker = "✅"
    inactive_marker = "⚪️"  # Or some other suitable unicode

    blacklist_marker = active_marker if current_mode == MuteListMode.blacklist else inactive_marker
    whitelist_marker = active_marker if current_mode == MuteListMode.whitelist else inactive_marker

    blacklist_text = _("{marker} Blacklist Mode").format(marker=blacklist_marker)
    whitelist_text = _("{marker} Whitelist Mode").format(marker=whitelist_marker)

    builder.button(
        text=blacklist_text,
        callback_data=AdminSetSubscriberMuteModeCallback(
            target_telegram_id=target_telegram_id,
            mode=MuteListMode.blacklist,
            subscriber_page_context=subscriber_page_context,
        ).pack(),
    )
    builder.button(
        text=whitelist_text,
        callback_data=AdminSetSubscriberMuteModeCallback(
            target_telegram_id=target_telegram_id,
            mode=MuteListMode.whitelist,
            subscriber_page_context=subscriber_page_context,
        ).pack(),
    )
    builder.adjust(1)  # Keep as single buttons for clarity, or 2 if space allows. Let's do 1.

    builder.row(
        InlineKeyboardButton(
            text=_("⬅️ Back to User Actions"),
            callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context).pack(),
        )
    )
    return builder.as_markup()


async def create_linkable_tt_account_list_keyboard(
    translator: gettext.GNUTranslations,  # Ensure _ type hint matches generic helper
    page_items: list[pytalk.UserAccount],
    current_page_idx: int,
    total_pages: int,
    target_telegram_id: int,
    subscriber_list_page: int,
) -> InlineKeyboardMarkup:
    """Creates keyboard for selecting a TeamTalk account to link to a subscriber, using generic helper."""
    _ = translator.gettext

    # Define the item_button_former for linkable TeamTalk accounts
    def tt_account_button_former(
        account_obj: pytalk.UserAccount,
        _page_num: int,  # current_page_idx from the generic helper call
        _translate: "Callable[[str], str]",  # _ function
    ) -> InlineKeyboardButton:
        username_str = ttstr(account_obj.username)
        button_text = username_str
        return InlineKeyboardButton(
            text=button_text,
            callback_data=LinkTTAccountChosenCallback(
                tt_username=username_str,
                target_telegram_id=target_telegram_id,
                # This 'page' is for the main subscriber list context, passed through.
                # 'page_num' (current_page_idx of this list) is not directly used in this callback data.
                page=subscriber_list_page,
            ).pack(),
        )

    # Define the "Back to Manage Account" button
    # This will be a list of lists for additional_buttons_bottom
    back_button = InlineKeyboardButton(
        text=_("⬅️ Back to Manage Account"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.MANAGE_TT_ACCOUNT,
            target_telegram_id=target_telegram_id,
            page=subscriber_list_page,  # This is the page of the subscriber action menu/subscriber list
        ).pack(),
    )
    bottom_buttons = [[back_button]]

    # For pagination of this specific list, if needed.
    # We need a callback data that can handle this.
    # Let's assume ManageTTAccountCallback could be used/extended with a new action.
    # For now, to make it work, we'll use ManageTTAccountCallback with LINK_NEW action,
    # but also pass target_telegram_id and subscriber_list_page, so the handler can reconstruct the state.
    # This is a bit of a workaround if this list itself needs pagination.
    # A dedicated PaginateLinkableTtAccountsCallback would be cleaner.
    # For this example, let's assume pagination needs to bring us back to the same view.
    # The ManageTTAccountCallback.LINK_NEW action handler would need to be aware of an
    # optional 'page_to_show' for its own list.

    # If this list is paginated, the LINK_NEW handler would need to accept a
    # `current_tt_account_page` or similar to re-render this list at the correct page.
    # For simplicity, and based on original comments, let's assume this list itself is
    # not paginated by its own callback for now.
    # So, pagination_callback_factory can be a dummy or raise an error if total_pages > 1,
    # or we simply don't provide it if the list is not meant to be paginated by the generic helper.
    # The original code did not have explicit pagination buttons for this list.
    # If total_pages is always 1 for this list, pagination controls won't be added by the generic helper.

    # Let's use a placeholder pagination factory that indicates this list's pagination isn't fully set up
    # through this generic helper yet, or rely on total_pages being 1.
    # If total_pages > 1, this would fail unless a proper factory is defined.
    # For now, we will pass a factory that would require a new CallbackData and handler action.
    # To avoid breaking things, if total_pages > 1, this setup will require a new callback.
    # Let's assume for now the caller ensures total_pages is 1, or pagination is handled outside.
    # To make it safe, we will use a dummy pagination_callback_factory if total_pages > 1 and
    # rely on the fact that the caller might handle pagination by slicing page_items.
    # The generic helper will add pagination if total_pages > 1.
    # We need *some* callback factory.
    # Use PaginateLinkableAccountsCallback for pagination of this list.
    # `page` in PaginateLinkableAccountsCallback is for the current list of linkable accounts.
    # `subscriber_context_page` and `target_telegram_id` are fixed for these pagination buttons.
    pagination_factory_kwargs = {
        "subscriber_context_page": subscriber_list_page,
        "target_telegram_id": target_telegram_id,
    }

    return await _create_generic_paginated_list_keyboard(
        translator=translator,
        page_items=page_items,
        current_page=current_page_idx,
        total_pages=total_pages,
        item_button_former=tt_account_button_former,
        pagination_callback_factory=PaginateLinkableAccountsCallback,  # Use the new callback
        pagination_factory_kwargs=pagination_factory_kwargs,
        additional_buttons_bottom=bottom_buttons,
    )


async def create_admin_subscriber_lang_keyboard(
    translator: gettext.GNUTranslations,
    available_languages: list[LanguageInfo],  # Changed here
    target_telegram_id: int,
    subscriber_page_context: int,  # Page of the main subscriber list
) -> InlineKeyboardMarkup:
    """Creates the language selection keyboard for an admin to change a subscriber's language."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    if not available_languages:
        # This case should ideally not happen if languages are configured
        builder.button(text=_("No languages available"), callback_data="noop_admin_lang_sel")
    else:
        for lang_info in available_languages:
            builder.button(
                text=lang_info["native_name"],
                callback_data=AdminSetSubscriberLanguageCallback(
                    target_telegram_id=target_telegram_id,
                    lang_code=lang_info["code"],
                    subscriber_page_context=subscriber_page_context,
                ).pack(),
            )

    builder.row(
        InlineKeyboardButton(
            text=_("⬅️ Back to User Actions"),
            callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context).pack(),
        )
    )
    builder.adjust(1)  # All buttons in a single column
    return builder.as_markup()


async def create_admin_subscriber_notification_pref_keyboard(
    translator: gettext.GNUTranslations,
    current_setting: NotificationSetting,  # The subscriber's current setting
    target_telegram_id: int,
    subscriber_page_context: int,
) -> InlineKeyboardMarkup:
    """Creates the notification preference selection keyboard for an admin to change for a subscriber."""
    _ = translator.gettext
    builder = InlineKeyboardBuilder()

    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", "all"),
        NotificationSetting.LEAVE_OFF: ("Join Only", "leave_off"),
        NotificationSetting.JOIN_OFF: ("Leave Only", "join_off"),
        NotificationSetting.NONE: ("None", "none"),
    }

    for setting_enum, (text_source, val_str) in settings_map_source.items():
        button_text = _("✅ {text}").format(text=_(text_source)) if current_setting == setting_enum else _(text_source)
        builder.button(
            text=button_text,
            callback_data=AdminSetSubscriberNotificationPrefCallback(
                target_telegram_id=target_telegram_id,
                setting_value=val_str,
                subscriber_page_context=subscriber_page_context,
            ).pack(),
        )

    builder.row(
        InlineKeyboardButton(
            text=_("⬅️ Back to User Actions"),
            callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context).pack(),
        )
    )
    builder.adjust(1)
    return builder.as_markup()
