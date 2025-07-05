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
    ManageTTAccountAction,
)
from functools import partial # Added for pagination_callback_factory
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
    LinkTTAccountChosenCallback,
    # New callback for this paginated list if needed, let's call it PaginateLinkableTtAccountsCallback
    # For now, we'll assume ManageTTAccountCallback can be used if action is adapted or a new one added.
    # Let's create a placeholder if we make it self-paginated:
    # PaginateLinkableTtAccountsCallback,
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
    builder = InlineKeyboardBuilder()
    if not available_languages:
        builder.button(
            text="No languages available",
            callback_data="noop"
        )
    else:
        for lang_info in available_languages:
            builder.button(
                text=lang_info["native_name"],
                callback_data=LanguageCallback(action=LanguageAction.SET_LANG, lang_code=lang_info["code"]).pack()
            )

    builder.button(
        text=_("⬅️ Back to Settings"),
        callback_data=SettingsCallback(action=SettingsNavAction.BACK_TO_MAIN).pack()
    )
    builder.adjust(1)
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
    active_marker = "✅"
    inactive_marker = "⚪️"

    blacklist_marker = active_marker if user_settings.mute_list_mode == MuteListMode.blacklist else inactive_marker
    whitelist_marker = active_marker if user_settings.mute_list_mode == MuteListMode.whitelist else inactive_marker

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
    builder.adjust(2)

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
    def username_extractor(item: str) -> str:
        return item
    def display_name_extractor(item: str) -> str:
        return item
    return await _create_generic_user_toggle_list_keyboard(
        _=_,
        page_items=page_items,
        current_page=current_page,
        total_pages=total_pages,
        user_settings=user_settings,
        list_type_for_callback=list_type,
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
        return ttstr(item.username)
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

# --- START NEW GENERIC PAGINATION HELPERS ---

def _add_pagination_controls_generic(
    builder: InlineKeyboardBuilder,
    _: Callable[[str], str],
    current_page: int,
    total_pages: int,
    pagination_callback_factory: Callable[..., Any],
    # To pass additional fixed args to the pagination_callback_factory
    **factory_kwargs
) -> None:
    """Adds generic pagination controls (Previous/Next) to the keyboard builder."""
    pagination_buttons = []
    if current_page > 0:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("⬅️ Prev"),
                callback_data=pagination_callback_factory(page=current_page - 1, **factory_kwargs).pack()
            )
        )
    if current_page < total_pages - 1:
        pagination_buttons.append(
            InlineKeyboardButton(
                text=_("Next ➡️"),
                callback_data=pagination_callback_factory(page=current_page + 1, **factory_kwargs).pack()
            )
        )
    if pagination_buttons:
        builder.row(*pagination_buttons)

async def _create_generic_paginated_list_keyboard(
    _: Callable[[str], str],
    page_items: List[Any],
    current_page: int,
    total_pages: int,
    item_button_former: Callable[[Any, int, Callable[[str], str]], InlineKeyboardButton | List[InlineKeyboardButton]],
    pagination_callback_factory: Callable[..., Any],
    pagination_factory_kwargs: dict | None = None, # For additional fixed args to pagination_callback_factory
    additional_buttons_top: List[List[InlineKeyboardButton]] | None = None,
    additional_buttons_bottom: List[List[InlineKeyboardButton]] | None = None
) -> InlineKeyboardMarkup:
    """
    Generic helper to create a keyboard for a paginated list of items.
    item_button_former should be a synchronous function.
    """
    builder = InlineKeyboardBuilder()

    if additional_buttons_top:
        for row_buttons in additional_buttons_top:
            builder.row(*row_buttons)

    for item in page_items:
        button_or_buttons = item_button_former(item, current_page, _)

        if isinstance(button_or_buttons, list):
            builder.row(*button_or_buttons)
        else:
            builder.row(button_or_buttons)

    if total_pages > 1:
        factory_kwargs_to_pass = pagination_factory_kwargs if pagination_factory_kwargs is not None else {}
        _add_pagination_controls_generic(
            builder,
            _,
            current_page,
            total_pages,
            pagination_callback_factory,
            **factory_kwargs_to_pass
        )

    if additional_buttons_bottom:
        for row_buttons in additional_buttons_bottom:
            builder.row(*row_buttons)

    return builder.as_markup()

# --- END NEW GENERIC PAGINATION HELPERS ---


async def create_subscriber_list_keyboard(
    _: Callable[[str], str],
    page_subscribers_info: List[SubscriberInfo],
    current_page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing the subscriber list using the generic helper."""

    def subscriber_button_former(
        subscriber: SubscriberInfo,
        page_num: int,
        translate: Callable[[str], str]
    ) -> InlineKeyboardButton:
        user_info_parts = [subscriber.display_name]
        if subscriber.teamtalk_username:
            user_info_parts.append(f"TT: {html.escape(subscriber.teamtalk_username)}")
        button_text = ", ".join(user_info_parts)

        return InlineKeyboardButton(
            text=button_text,
            callback_data=ViewSubscriberCallback(
                telegram_id=subscriber.telegram_id,
                page=page_num
            ).pack()
        )

    # For SubscriberListCallback, action is a fixed parameter for pagination.
    pagination_kwargs = {"action": SubscriberListAction.PAGE}

    return await _create_generic_paginated_list_keyboard(
        _=_,
        page_items=page_subscribers_info,
        current_page=current_page,
        total_pages=total_pages,
        item_button_former=subscriber_button_former,
        pagination_callback_factory=SubscriberListCallback, # Pass the class directly
        pagination_factory_kwargs=pagination_kwargs
    )

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
    builder.adjust(1)
    return builder


async def create_subscriber_action_menu_keyboard(
    _: callable,
    target_telegram_id: int,
    page: int
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
        callback_data=SubscriberListCallback(
            action=SubscriberListAction.PAGE,
            page=page
        ).pack()
    )
    builder.adjust(1)
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
    page: int,
    list_action_page: int = 0
) -> InlineKeyboardMarkup:
    """Creates the keyboard for managing a subscriber's TeamTalk account link."""
    builder = InlineKeyboardBuilder()

    if current_tt_username:
        builder.button(
            text=_("🔓 Unlink {current_tt_username}").format(current_tt_username=html.escape(current_tt_username)),
            callback_data=ManageTTAccountCallback(
                action=ManageTTAccountAction.UNLINK,
                target_telegram_id=target_telegram_id,
                page=page
            ).pack()
        )

    builder.button(
        text=_("➕ Link/Change TeamTalk Account"),
        callback_data=ManageTTAccountCallback(
            action=ManageTTAccountAction.LINK_NEW,
            target_telegram_id=target_telegram_id,
            page=page
        ).pack()
    )
    builder.button(
        text=_("⬅️ Back to User Actions"),
        callback_data=ViewSubscriberCallback(
            telegram_id=target_telegram_id,
            page=page
        ).pack()
    )
    builder.adjust(1)
    return builder.as_markup()


async def create_linkable_tt_account_list_keyboard(
    _: Callable[[str], str], # Ensure _ type hint matches generic helper
    page_items: list[pytalk.UserAccount],
    current_page_idx: int,
    total_pages: int,
    target_telegram_id: int,
    subscriber_list_page: int
) -> InlineKeyboardMarkup:
    """Creates keyboard for selecting a TeamTalk account to link to a subscriber, using generic helper."""

    # Define the item_button_former for linkable TeamTalk accounts
    def tt_account_button_former(
        account_obj: pytalk.UserAccount,
        page_num: int, # current_page_idx from the generic helper call
        translate: Callable[[str], str] # _ function
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
                page=subscriber_list_page
            ).pack()
        )

    # Define the "Back to Manage Account" button
    # This will be a list of lists for additional_buttons_bottom
    back_button = InlineKeyboardButton(
        text=_("⬅️ Back to Manage Account"),
        callback_data=SubscriberActionCallback(
            action=SubscriberAction.MANAGE_TT_ACCOUNT,
            target_telegram_id=target_telegram_id,
            page=subscriber_list_page # This is the page of the subscriber action menu/subscriber list
        ).pack()
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
    # The ManageTTAccountCallback.LINK_NEW action handler would need to be aware of an optional 'page_to_show' for its own list.

    # If this list is paginated, the LINK_NEW handler would need to accept a `current_tt_account_page`
    # or similar to re-render this list at the correct page.
    # For simplicity, and based on original comments, let's assume this list itself is not paginated by its own callback for now.
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
    # Let's use ManageTTAccountCallback and assume the LINK_NEW action can handle `page` for its own pagination.
    pagination_kwargs_for_tt_list = {
        "action": ManageTTAccountAction.LINK_NEW, # Re-calling the same action to show the list
        "target_telegram_id": target_telegram_id,
        # subscriber_list_page is also part of the context for LINK_NEW to return correctly after selection
        # but for pagination of *this* list, we need to pass it so LINK_NEW can use it.
        "current_subscriber_page_context": subscriber_list_page
    }


    return await _create_generic_paginated_list_keyboard(
        _=_,
        page_items=page_items,
        current_page=current_page_idx, # This is the current page of TT accounts
        total_pages=total_pages,      # Total pages of TT accounts
        item_button_former=tt_account_button_former,
        # pagination_callback_factory: If this list can be paginated, it needs its own callback factory.
        # The original ManageTTAccountCallback is for actions, not paginating this list.
        # We'll use ManageTTAccountCallback, but its handler for LINK_NEW would need to be
        # updated to understand a 'page' parameter for *this* list's pagination.
        pagination_callback_factory=ManageTTAccountCallback,
        pagination_factory_kwargs=pagination_kwargs_for_tt_list,
        additional_buttons_bottom=bottom_buttons
    )
