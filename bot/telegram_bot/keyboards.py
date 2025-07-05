"""
Keyboard utilities for the Telegram bot.

This module provides functions to generate and manage custom keyboards
for Telegram interactions using InlineKeyboardBuilder.
"""

import html
import pytalk # For UserAccount type hint
from typing import Callable, List, Any # Added Any for the generic helper
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.telegram_bot.models import SubscriberInfo

from bot.core.enums import (
    AdminAction,
    SettingsNavAction,
    LanguageAction,
    SubscriptionAction,
    NotificationAction,
    UserListAction,
    ToggleMuteSpecificAction,
    SubscriberListAction,
    SubscriberAction,
    ManageTTAccountAction
)
from bot.telegram_bot.callback_data import (
    SettingsCallback,
    LanguageCallback,
    SubscriptionCallback,
    NotificationActionCallback,
    SetMuteModeCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback,
    AdminActionCallback,
    SubscriberListCallback,
    MenuCallback,
    ViewSubscriberCallback,
    SubscriberActionCallback,
    ManageTTAccountCallback,
    LinkTTAccountChosenCallback
)
from bot.models import NotificationSetting, UserSettings, MuteListMode
from bot.core.utils import get_tt_user_display_name

ttstr = pytalk.instance.sdk.ttstr


# --- Helper Functions ---

def _is_username_effectively_muted(username: str, user_settings: UserSettings, muted_usernames_set: set[str]) -> bool:
    """
    Determines if a username is effectively muted based on user settings and a provided set of muted/allowed usernames.
    - If user_settings.mute_all is True, the set is an allow list; user is muted if NOT in the set.
    - If user_settings.mute_all is False, the set is a block list; user is muted if IN the set.
    """
    is_in_set = username in muted_usernames_set
    if user_settings.mute_list_mode == MuteListMode.whitelist:
        return not is_in_set  # Muted if not in the allow list
    else: # blacklist mode
        return is_in_set      # Muted if in the block list

# --- Settings Keyboards ---

async def create_main_settings_keyboard(_: callable) -> InlineKeyboardBuilder:
    """Creates the main settings menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_("Language"),
        callback_data=SettingsCallback(action=SettingsNavAction.LANGUAGE).pack()
    )
    builder.button(
        text=_("Subscription Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.SUBSCRIPTIONS).pack()
    )
    builder.button(
        text=_("Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack()
    )
    builder.adjust(1)
    return builder

async def create_language_selection_keyboard(_: callable, available_languages: list) -> InlineKeyboardBuilder:
    """Creates the language selection keyboard dynamically."""
    # from bot.core.languages import AVAILABLE_LANGUAGES_DATA # Removed import

    builder = InlineKeyboardBuilder()
    if not available_languages: # Use passed argument
        # Fallback or error message if no languages are discovered
        # This case should ideally be handled by ensuring default lang is always present
        builder.button(
            text="No languages available", # This ideally should be translatable too
            callback_data="noop" # A dummy callback or specific error callback
        )
    else:
        for lang_info in available_languages: # Use passed argument
            builder.button(
                text=lang_info["native_name"], # Already translated to its native form
                callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code=lang_info["code"]).pack()
            )

    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1) # Adjust based on number of languages, or keep 1 per row
    return builder

async def create_subscription_settings_keyboard(
    _: callable,
    current_setting: NotificationSetting
) -> InlineKeyboardBuilder:
    """Creates the subscription settings keyboard."""
    builder = InlineKeyboardBuilder()

    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", "all"),
        NotificationSetting.LEAVE_OFF: ("Join Only", "leave_off"),
        NotificationSetting.JOIN_OFF: ("Leave Only", "join_off"),
        NotificationSetting.NONE: ("None", "none"),
    }

    for setting_enum, (text_source, val_str) in settings_map_source.items():
        if current_setting == setting_enum:
            button_text = _("✅ {text}").format(text=_(text_source))
        else:
            button_text = _(text_source)

        builder.button(
            text=button_text,
            callback_data=SubscriptionCallback(action=SubscriptionAction.SET_SUB, setting_value=val_str).pack()
        )

    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

async def create_notification_settings_keyboard(
    _: callable,
    user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the notification settings keyboard."""
    builder = InlineKeyboardBuilder()

    is_noon_enabled = user_settings.not_on_online_enabled
    status_text = _("Enabled") if is_noon_enabled else _("Disabled")
    noon_button_text = _("NOON (Not on Online): {status}").format(status=status_text)

    builder.button(
        text=noon_button_text,
        callback_data=NotificationActionCallback(action=NotificationAction.TOGGLE_NOON).pack()
    )
    builder.button(
        text=_("Manage Mute List"),
        callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack()
    )
    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
    return builder

async def create_manage_muted_users_keyboard(
    _: callable,
    user_settings: UserSettings
) -> InlineKeyboardBuilder:
    """Creates the 'Manage Mute List' keyboard."""
    builder = InlineKeyboardBuilder()
    active_marker = "✅"  # Space removed, will be in translatable string
    inactive_marker = "⚪️" # Space removed, will be in translatable string

    # Determine markers based on current mode
    blacklist_marker = active_marker if user_settings.mute_list_mode == MuteListMode.blacklist else inactive_marker
    whitelist_marker = active_marker if user_settings.mute_list_mode == MuteListMode.whitelist else inactive_marker

    # Use .format() on the translated string
    blacklist_text = _("{marker} Blacklist Mode").format(marker=blacklist_marker)
    whitelist_text = _("{marker} Whitelist Mode").format(marker=whitelist_marker)

    builder.button(
        text=blacklist_text,
        callback_data=SetMuteModeCallback(mode=MuteListMode.blacklist).pack()
    )
    builder.button(
        text=whitelist_text,
        callback_data=SetMuteModeCallback(mode=MuteListMode.whitelist).pack()
    )
    builder.adjust(2) # Display side-by-side

    # Dynamic button text for managing the list
    list_mode_text = _("Manage Blacklist") if user_settings.mute_list_mode == MuteListMode.blacklist else _("Manage Whitelist")
    builder.button(
        text=list_mode_text,
        callback_data=UserListCallback(action=UserListAction.LIST_MUTED).pack()
    )

    builder.button(
        text=_("Mute/Unmute from Server List"),
        callback_data=UserListCallback(action=UserListAction.LIST_ALL_ACCOUNTS).pack()
    )
    builder.button(
        text=_("⬅️ Back to Notification Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.NOTIFICATIONS).pack()
    )
    builder.adjust(1)
    return builder

# --- Paginated List Keyboards ---

async def _add_pagination_controls(
    builder: InlineKeyboardBuilder,
    _: callable,
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    callback_factory: Callable
) -> None:
    """Adds pagination controls (Previous/Next) to the keyboard builder."""
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=callback_factory(list_type=list_type, page=current_page - 1).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=callback_factory(list_type=list_type, page=current_page + 1).pack()
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)


async def create_paginated_user_list_keyboard(
    _: callable,
    page_items: list[str],
    current_page: int,
    total_pages: int,
    list_type: UserListAction,
    user_settings: UserSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of internal (muted/allowed) users."""

    # Define extractors for the generic helper
    # For this function, the item in page_items is already the username string.
    def username_extractor(item: str) -> str:
        return item

    def display_name_extractor(item: str) -> str:
        return item

    # The button text format in the generic helper is "{display_name} (Status: {status_text})".
    # The original format was "Unmute {username}" or "Mute {username}".
    # We will rely on the generic helper's new standardized format.

    return await _create_generic_user_toggle_list_keyboard(
        _=_,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=list_type, # list_type is passed in, e.g. UserListAction.LIST_MUTED
        item_username_extractor=username_extractor,
        item_display_name_extractor=display_name_extractor,
        back_button_callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack(),
        back_button_text_key="⬅️ Back to Mute Management"
    )

async def create_account_list_keyboard(
    _: callable,
    page_items: list[pytalk.UserAccount],
    current_page: int,
    total_pages: int,
    user_settings: UserSettings
) -> InlineKeyboardMarkup:
    """Creates keyboard for a paginated list of all server user accounts."""

    def username_extractor(item: pytalk.UserAccount) -> str:
        return ttstr(item.username)

    def display_name_extractor(item: pytalk.UserAccount) -> str:
        return ttstr(item.username) # Display name is also the username for this list

    return await _create_generic_user_toggle_list_keyboard(
        _=_,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=UserListAction.LIST_ALL_ACCOUNTS,
        item_username_extractor=username_extractor,
        item_display_name_extractor=display_name_extractor,
        back_button_callback_data=NotificationActionCallback(action=NotificationAction.MANAGE_MUTED).pack(),
        back_button_text_key="⬅️ Back to Mute Management"
    )

async def create_subscriber_list_keyboard(
    _: Callable,
    page_subscribers_info: List[SubscriberInfo],
    current_page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the subscriber list."""
    builder = InlineKeyboardBuilder()

    for subscriber in page_subscribers_info:
        user_info_parts = [subscriber.display_name]
        if subscriber.teamtalk_username:
            user_info_parts.append(f"TT: {html.escape(subscriber.teamtalk_username)}")

        button_text = ", ".join(user_info_parts) # This is the display text for the button

        builder.row(
            InlineKeyboardButton(
                text=button_text, # Display user info
                callback_data=ViewSubscriberCallback( # New callback to view details
                    telegram_id=subscriber.telegram_id,
                    page=current_page
                ).pack()
            )
        )

    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=SubscriberListCallback(
                    action=SubscriberListAction.PAGE,
                    page=current_page - 1
                ).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=SubscriberListCallback(
                    action=SubscriberListAction.PAGE,
                    page=current_page + 1
                ).pack()
            )
        )

    if pagination_buttons:
        builder.row(*pagination_buttons)

    return builder.as_markup()

async def create_user_selection_keyboard(
    _: callable,
    users_to_display: list[pytalk.user.User],
    command_type: AdminAction
) -> InlineKeyboardBuilder:
    """
    Creates a keyboard with buttons for each user in the provided list.
    """
    builder = InlineKeyboardBuilder()

    for user_obj in users_to_display:
        if not user_obj:
            continue

        user_nickname = get_tt_user_display_name(user_obj, _)

        if not hasattr(user_obj, 'id'):
            continue
        user_id = user_obj.id

        callback_data = AdminActionCallback(
            action=command_type,
            user_id=user_id
        ).pack()

        builder.button(
            text=html.escape(user_nickname),
            callback_data=callback_data
        )

    builder.adjust(2)
    return builder


async def create_main_menu_keyboard(_: callable, is_admin: bool) -> InlineKeyboardBuilder:
    """Creates the main menu keyboard with commands."""
    builder = InlineKeyboardBuilder()

    # Common user commands
    builder.button(
        text=_("ℹ️ Who is online?"),
        callback_data=MenuCallback(command="who").pack()
    )
    builder.button(
        text=_("⚙️ Settings"),
        callback_data=MenuCallback(command="settings").pack()
    )
    builder.button(
        text=_("❓ Help"),
        callback_data=MenuCallback(command="help").pack()
    )

    if is_admin:
        builder.button(
            text=_("👢 Kick User"),
            callback_data=MenuCallback(command="kick").pack()
        )
        builder.button(
            text=_("🚫 Ban User"),
            callback_data=MenuCallback(command="ban").pack()
        )
        builder.button(
            text=_("👥 Subscribers"),
            callback_data=MenuCallback(command="subscribers").pack()
        )

    builder.adjust(1) # Adjust to show one button per row for a cleaner look
    return builder


async def create_subscriber_action_menu_keyboard(
    _: callable,
    target_telegram_id: int,
    page: int # Page of the main subscriber list to return to
) -> InlineKeyboardMarkup:
    """Creates the action menu for a specific subscriber."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_("🗑️ Delete Subscriber"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.DELETE,
            target_telegram_id=target_telegram_id,
            page=page
        ).pack()
    )
    builder.button(
        text=_("🚫 Ban User (TG & TT)"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.BAN,
            target_telegram_id=target_telegram_id,
            page=page
        ).pack()
    )
    builder.button(
        text=_("🔗 Manage TeamTalk Account"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.MANAGE_TT_ACCOUNT,
            target_telegram_id=target_telegram_id,
            page=page
        ).pack()
    )
    builder.button(
        text=_("⬅️ Back to Subscribers List"),
        callback_data=SubscriberListCallback( # This should go back to the list view
            action=SubscriberListAction.PAGE, # Existing action for pagination
            page=page                         # The page number of the list we came from
        ).pack()
    )
    builder.adjust(1) # One button per row
    return builder.as_markup()

# --- Generic Helper for Paginated User Lists with Toggle ---
async def _create_generic_user_toggle_list_keyboard(
    _: Callable[[str], str],
    page_items: List[Any],
    current_page: int,
    total_pages: int,
    user_settings: UserSettings,
    list_type_for_callback: UserListAction,
    item_username_extractor: Callable[[Any], str],
    item_display_name_extractor: Callable[[Any], str],
    back_button_callback_data: str,
    back_button_text_key: str
) -> InlineKeyboardMarkup:
    """
    Generic helper to create a keyboard for a paginated list of users
    with mute/unmute toggle buttons.
    """
    builder = InlineKeyboardBuilder()

    muted_usernames_from_relationship = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}

    for idx, item in enumerate(page_items):
        username_str = item_username_extractor(item)
        display_name_on_button = item_display_name_extractor(item)

        effectively_muted = _is_username_effectively_muted(username_str, user_settings, muted_usernames_from_relationship)

        # Вместо двух отдельных msgid, создаем один шаблон
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
            list_type=list_type_for_callback
        ).pack()
        builder.button(text=button_text, callback_data=callback_d)

    if page_items:
        builder.adjust(1)

    await _add_pagination_controls(builder, _, current_page, total_pages, list_type_for_callback, PaginateUsersCallback)

    builder.row(InlineKeyboardButton(
        text=_(back_button_text_key),
        callback_data=back_button_callback_data
    ))
    return builder.as_markup()


async def create_manage_tt_account_keyboard(
    _: callable,
    target_telegram_id: int,
    current_tt_username: str | None,
    page: int, # Page of the main subscriber list to return to (via subscriber action menu)
    list_action_page: int = 0 # Page of the TT account list, if paginated
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing a subscriber's TeamTalk account link."""
    builder = InlineKeyboardBuilder()

    if current_tt_username:
        builder.button(
            text=_("🔓 Unlink {current_tt_username}").format(current_tt_username=html.escape(current_tt_username)),
            callback_data=ManageTTAccountCallback(
                action=ManageTTAccountAction.UNLINK,
                target_telegram_id=target_telegram_id,
                page=page # This 'page' is for returning to subscriber list via action menu
            ).pack()
        )

    builder.button(
        text=_("➕ Link/Change TeamTalk Account"),
        callback_data=ManageTTAccountCallback(
            action=ManageTTAccountAction.LINK_NEW,
            target_telegram_id=target_telegram_id,
            page=page # This 'page' is for returning to subscriber list via action menu
        ).pack()
    )

    # Button to go back to the specific subscriber's action menu
    builder.button(
        text=_("⬅️ Back to User Actions"),
        callback_data=ViewSubscriberCallback( # Use ViewSubscriberCallback to go back to the action menu
            telegram_id=target_telegram_id,
            page=page # This 'page' is for the subscriber list page context
        ).pack()
    )
    builder.adjust(1)
    return builder.as_markup()


async def create_linkable_tt_account_list_keyboard(
    _: callable,
    page_items: list[pytalk.UserAccount], # Same items as mute list
    current_page_idx: int, # Renamed to avoid confusion with subscriber list page
    total_pages: int,
    target_telegram_id: int, # The TG user we are linking for
    subscriber_list_page: int # The page of the main subscriber list to return to eventually
) -> InlineKeyboardMarkup:
    """Creates keyboard for selecting a TeamTalk account to link to a subscriber."""
    builder = InlineKeyboardBuilder()

    for account_obj in page_items: # account_obj is pytalk.UserAccount
        username_str = ttstr(account_obj.username)
        # We don't need to show mute status here, just the username to link
        button_text = username_str

        callback_d = LinkTTAccountChosenCallback(
            tt_username=username_str,
            target_telegram_id=target_telegram_id,
            page=subscriber_list_page # This page is for the main subscriber list context
            # If this account list itself becomes paginated, LinkTTAccountChosenCallback would need current_page_idx too
        )
        builder.button(text=button_text, callback_data=callback_d.pack())

    if page_items:
        builder.adjust(1) # One account per row for clarity

    # Pagination for this TT account list (if it becomes paginated in future, for now assumes one page or handled by caller)
    # For now, let's assume the caller of this keyboard handles pagination of page_items if needed,
    # and this keyboard just renders the current page of TT accounts.
    # If pagination is added for *this* list, a different callback for its pagination is needed.

    # Back button to the "Manage TT Account" menu for the specific subscriber
    builder.row(InlineKeyboardButton(
        text=_("⬅️ Back to Manage Account"),
        callback_data=SubscriberActionCallback( # This takes us back to the manage_tt action, which will re-render the manage_tt_account_keyboard
            action=SubscriberAction.MANAGE_TT_ACCOUNT,
            target_telegram_id=target_telegram_id,
            page=subscriber_list_page
        ).pack()
    ))
    return builder.as_markup()
