import logging
import math
from typing import Callable, Any
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk # For ttstr
from pytalk.instance import TeamTalkInstance

from bot.core.user_settings import UserSpecificSettings, update_user_settings_in_db
from bot.telegram_bot.keyboards import (
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
    create_account_list_keyboard
)
from bot.telegram_bot.callback_data import (
    NotificationActionCallback, # For manage_muted entry point
    MuteAllCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback
)
from bot.constants import USERS_PER_PAGE
from bot.state import USER_ACCOUNTS_CACHE # For listing all server accounts
from ._helpers import process_setting_update # For mute_all toggle

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
ttstr = pytalk.instance.sdk.ttstr

# --- Helper Functions (originally in callbacks.py, now localized or adapted) ---

def _paginate_list_util(full_list: list, page: int, page_size: int) -> tuple[list, int, int]:
    total_items = len(full_list)
    total_pages = int(math.ceil(total_items / page_size)) if total_items > 0 else 1
    page = max(0, min(page, total_pages - 1)) # Ensure page is within bounds
    start_index = page * page_size
    end_index = start_index + page_size
    page_slice = full_list[start_index:end_index]
    return page_slice, total_pages, page

async def _display_paginated_list_ui(
    callback_query: CallbackQuery,
    _: callable,
    items: list,
    page: int,
    header_text_key: str,
    empty_list_text_key: str,
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
    keyboard_factory_kwargs: dict
) -> None:
    if not callback_query.message:
        return

    page_slice, total_pages, current_page_idx = _paginate_list_util(items, page, USERS_PER_PAGE)

    message_parts = [_(header_text_key)]
    if not items:
        message_parts.append(_(empty_list_text_key))

    page_indicator_text = _("Page {current_page}/{total_pages}").format(current_page=current_page_idx + 1, total_pages=total_pages) # PAGE_INDICATOR
    message_parts.append(f"\n{page_indicator_text}")

    final_message_text = "\n".join(message_parts)

    keyboard_markup = keyboard_factory(
        _=_,
        page_items=page_slice,
        current_page=current_page_idx,
        total_pages=total_pages,
        **keyboard_factory_kwargs
    )

    try:
        await callback_query.message.edit_text(
            text=final_message_text,
            reply_markup=keyboard_markup,
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest in _display_paginated_list_ui for {header_text_key}: {e}", exc_info=True)
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError in _display_paginated_list_ui for {header_text_key}: {e}", exc_info=True)


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    list_type: str, # "muted" or "allowed" (this is the *effective* list type to display)
    page: int = 0
):
    if not callback_query.message: return

    users_to_process = user_specific_settings.muted_users_set
    sorted_items = sorted(list(users_to_process))

    is_mute_all_active = user_specific_settings.mute_all_flag

    if list_type == "muted":
        header_key = "MUTED_USERS_HEADER"
        empty_key = "NO_MUTED_USERS_TEXT"
        if is_mute_all_active: # This means we are showing 'muted_users_set' as a block list, even if Mute All is ON.
                               # This scenario should be rare if cq_list_internal_users_action correctly redirects.
            logger.info("Displaying 'muted' (block list interpretation) while Mute All is ON.")
    elif list_type == "allowed":
        header_key = "ALLOWED_USERS_HEADER"
        empty_key = "NO_ALLOWED_USERS_TEXT"
        if not is_mute_all_active: # This means we are showing 'muted_users_set' as an allow list, even if Mute All is OFF.
                                  # Also rare if cq_list_internal_users_action redirects.
            logger.info("Displaying 'allowed' (allow list interpretation) while Mute All is OFF.")
    else:
        logger.error(f"Unknown list_type '{list_type}' in _display_internal_user_list")
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        return

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key=header_key,
        empty_list_text_key=empty_key,
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={
            "list_type": list_type,
            "user_specific_settings": user_specific_settings
        }
    )

async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance,
    page: int = 0
):
    if not callback_query.message: return

    if not USER_ACCOUNTS_CACHE:
        try:
            await callback_query.message.edit_text(_("SERVER_ACCOUNTS_NOT_LOADED_TEXT"))
        except TelegramAPIError as e:
            logger.error(f"Error informing user about empty USER_ACCOUNTS_CACHE: {e}")
        return

    all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
    sorted_items = sorted(
        all_accounts_tt,
        key=lambda acc: ttstr(acc.username).lower()
    )

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key="ALL_SERVER_ACCOUNTS_HEADER",
        empty_list_text_key="NO_SERVER_ACCOUNTS_TEXT",
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={
            "user_specific_settings": user_specific_settings
        }
    )

# --- Main Callback Handlers ---

@mute_router.callback_query(NotificationActionCallback.filter(F.action == "manage_muted"))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback # Consumed by filter
):
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()
    manage_muted_builder = create_manage_muted_users_keyboard(_, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=_("MANAGE_MUTED_MENU_HEADER"),
            reply_markup=manage_muted_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for manage_muted_users menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for manage_muted_users menu: {e}")

@mute_router.callback_query(MuteAllCallback.filter(F.action == "toggle_mute_all"))
async def cq_toggle_mute_all_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: MuteAllCallback # Consumed by filter
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer(_("Error: Missing data for Mute All toggle."), show_alert=True)
        return

    original_flag = user_specific_settings.mute_all_flag

    def update_logic():
        user_specific_settings.mute_all_flag = not original_flag

    def revert_logic():
        user_specific_settings.mute_all_flag = original_flag

    new_status_text_key = "ENABLED_STATUS" if not original_flag else "DISABLED_STATUS"
    new_status_display_text = _(new_status_text_key)
    success_toast_text = _("MUTE_ALL_UPDATED_TO").format(status=new_status_display_text)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_manage_muted_users_keyboard(_, user_specific_settings)
        menu_text = _("MANAGE_MUTED_MENU_HEADER")
        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable
    )

@mute_router.callback_query(UserListCallback.filter(F.action.in_(["list_muted", "list_allowed"])))
async def cq_list_internal_users_action(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: UserListCallback
):
    await callback_query.answer()
    requested_list_type = callback_data.action.split("_")[1]

    is_mute_all_active = user_specific_settings.mute_all_flag

    effective_list_type = requested_list_type
    alert_message_key: str | None = None

    if requested_list_type == "muted" and is_mute_all_active:
        effective_list_type = "allowed"
        alert_message_key = "MUTE_ALL_ON_SHOWING_ALLOWED_TEXT"
    elif requested_list_type == "allowed" and not is_mute_all_active:
        effective_list_type = "muted"
        alert_message_key = "MUTE_ALL_OFF_SHOWING_MUTED_TEXT"

    if alert_message_key:
        try: # Show an alert if we switched the list type
            await callback_query.answer(_(alert_message_key), show_alert=True)
        except TelegramAPIError: pass # Non-critical if alert fails

    await _display_internal_user_list(callback_query, _, user_specific_settings, effective_list_type, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_(["muted", "allowed"])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    await _display_internal_user_list(
        callback_query, _, user_specific_settings, callback_data.list_type, callback_data.page
    )

@mute_router.callback_query(UserListCallback.filter(F.action == "list_all_accounts"))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: UserListCallback # Consumed by filter
):
    await callback_query.answer()
    if not callback_query.message: return
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TT_BOT_NOT_CONNECTED_FOR_USERS_TEXT"))
        return
    if not USER_ACCOUNTS_CACHE:
        await callback_query.message.edit_text(_("NO_SERVER_ACCOUNTS_LOADED_TEXT"))
        return

    await _display_all_server_accounts_list(callback_query, _, user_specific_settings, tt_instance, 0)

@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == "all_accounts"))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    if not callback_query.message: return
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TT_BOT_NOT_CONNECTED_FOR_USERS_TEXT"))
        return
    if not USER_ACCOUNTS_CACHE: # Check again, could have changed
        await callback_query.message.edit_text(_("NO_SERVER_ACCOUNTS_LOADED_TEXT"))
        return

    await _display_all_server_accounts_list(
        callback_query, _, user_specific_settings, tt_instance, callback_data.page
    )

@mute_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == "toggle_user"))
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: ToggleMuteSpecificCallback
):
    if not callback_query.message or not callback_query.from_user: return

    user_idx = callback_data.user_idx
    current_page_for_refresh = callback_data.current_page
    list_type_user_was_on = callback_data.list_type

    username_to_toggle: str | None = None

    if list_type_user_was_on == "all_accounts":
        if not USER_ACCOUNTS_CACHE:
            await callback_query.answer(_("SERVER_ACCOUNTS_UNAVAILABLE_TOAST"), show_alert=True)
            return
        all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
        sorted_accounts = sorted(all_accounts_tt, key=lambda acc: ttstr(acc.username).lower())

        page_items, _total_pages_discard, _page_idx_discard = _paginate_list_util(sorted_accounts, current_page_for_refresh, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            target_account = page_items[user_idx]
            username_to_toggle = ttstr(target_account.username)
        else:
            logger.warning(f"Invalid user_idx {user_idx} for all_accounts page {current_page_for_refresh}.")

    elif list_type_user_was_on in ["muted", "allowed"]:
        relevant_usernames = sorted(list(user_specific_settings.muted_users_set))
        page_items, _total_pages_discard, _page_idx_discard = _paginate_list_util(relevant_usernames, current_page_for_refresh, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            username_to_toggle = page_items[user_idx]
        else:
            logger.warning(f"Invalid user_idx {user_idx} for {list_type_user_was_on} page {current_page_for_refresh}.")
    else:
        logger.error(f"Unknown list_type '{list_type_user_was_on}' in toggle_user.")
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        return

    if not username_to_toggle:
        logger.error(f"Could not find username for toggle. Idx: {user_idx}, List: {list_type_user_was_on}, Page: {current_page_for_refresh}")
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        # Attempt to refresh the list they were on, if possible
        if list_type_user_was_on == "all_accounts":
            if tt_instance and tt_instance.connected and tt_instance.logged_in:
                 await _display_all_server_accounts_list(callback_query, _, user_specific_settings, tt_instance, current_page_for_refresh)
            else: # Can't refresh, go to main mute menu
                 await cq_show_manage_muted_menu(callback_query, _, user_specific_settings, NotificationActionCallback(action="manage_muted")) # type: ignore
        elif list_type_user_was_on in ["muted", "allowed"]:
             await _display_internal_user_list(callback_query, _, user_specific_settings, list_type_user_was_on, current_page_for_refresh)
        return

    # Perform toggle on the canonical set
    user_was_in_set = username_to_toggle in user_specific_settings.muted_users_set
    if user_was_in_set:
        user_specific_settings.muted_users_set.discard(username_to_toggle)
    else:
        user_specific_settings.muted_users_set.add(username_to_toggle)

    user_is_in_set_after_toggle = not user_was_in_set

    is_mute_all_active = user_specific_settings.mute_all_flag
    effectively_muted_after_toggle: bool
    if is_mute_all_active:
        effectively_muted_after_toggle = not user_is_in_set_after_toggle
    else:
        effectively_muted_after_toggle = user_is_in_set_after_toggle

    quoted_username = html.quote(username_to_toggle)
    if list_type_user_was_on in ["muted", "allowed"]:
        toast_message_key = "USER_UNMUTED_TOAST" if not effectively_muted_after_toggle else "USER_MUTED_TOAST"
        toast_message = _(toast_message_key).format(username=quoted_username)
    else: # "all_accounts"
        status_for_toast_key = "MUTED_STATUS" if effectively_muted_after_toggle else "NOT_MUTED_STATUS"
        toast_message = _("USER_MUTE_STATUS_UPDATED_TOAST").format(
            username=quoted_username,
            status=_(status_for_toast_key)
        )

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
        await callback_query.answer(toast_message, show_alert=False)
    except Exception as e:
        logger.error(f"DB/Answer error for {username_to_toggle}: {e}", exc_info=True)
        # Revert in-memory change
        if user_is_in_set_after_toggle:
            user_specific_settings.muted_users_set.discard(username_to_toggle)
        else:
            user_specific_settings.muted_users_set.add(username_to_toggle)
        try:
            await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        except TelegramAPIError: pass
        return

    # Refresh UI
    if list_type_user_was_on == "all_accounts":
        if tt_instance and tt_instance.connected and tt_instance.logged_in:
            await _display_all_server_accounts_list(callback_query, _, user_specific_settings, tt_instance, current_page_for_refresh)
        else:
            await callback_query.answer(_("TT_BOT_DISCONNECTED_REFRESH_FAILED_TOAST"), show_alert=True)
            await cq_show_manage_muted_menu(callback_query, _, user_specific_settings, NotificationActionCallback(action="manage_muted")) # type: ignore
    elif list_type_user_was_on in ["muted", "allowed"]:
        # The list type the user was on might need to change based on Mute All status
        # e.g., if they were on "allowed", but Mute All got turned OFF, they should see "muted"
        current_mute_all_status = user_specific_settings.mute_all_flag
        effective_list_to_refresh = list_type_user_was_on # Default to what they were viewing

        if list_type_user_was_on == "muted" and current_mute_all_status: # Was viewing block list, but Mute All is now ON
            effective_list_to_refresh = "allowed" # Show allow list instead
        elif list_type_user_was_on == "allowed" and not current_mute_all_status: # Was viewing allow list, but Mute All is now OFF
            effective_list_to_refresh = "muted" # Show block list instead

        await _display_internal_user_list(callback_query, _, user_specific_settings, effective_list_to_refresh, current_page_for_refresh)
    else:
        logger.error(f"Unknown list_type '{list_type_user_was_on}' for refresh in toggle_user")
