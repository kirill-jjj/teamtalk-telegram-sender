"""Callback query handlers for actions related to specific subscribers."""

import gettext
import logging
from typing import TYPE_CHECKING, Optional  # Added Optional

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
import pytalk
from sqlalchemy.orm import selectinload
from sqlmodel import select  # Moved here
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.constants import MUTE_LIST_ITEMS_PER_PAGE  # Moved here
from bot.core.enums import SubscriberAction
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.services import admin_service, user_service  # Added admin_service
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    LinkTTAccountChosenCallback,
    PaginateLinkableAccountsCallback,
    PaginateMuteListCallback,  # New
    SubscriberActionCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.keyboards import (
    create_admin_subscriber_lang_keyboard,
    create_admin_subscriber_mute_mode_keyboard,
    create_admin_subscriber_notification_pref_keyboard,
    create_linkable_tt_account_list_keyboard,
    create_manage_tt_account_keyboard,
    create_subscriber_action_menu_keyboard,  # Added back
    create_subscriber_list_keyboard,
    create_view_mute_list_keyboard,
)
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware
from bot.telegram_bot.utils import format_telegram_user_display_name

from .list_utils import SUBSCRIBERS_PER_PAGE, _get_paginated_subscribers_info

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
subscriber_actions_router = Router(name="subscriber_actions_router")
subscriber_actions_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
subscriber_actions_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    services: "Services",
    return_page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Refreshes and displays the paginated list of subscribers."""
    _ = translator.gettext
    active_bot = services.bot_event
    if not query.message:
        logger.warning("_refresh_and_display_subscriber_list called with no message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    message_obj = query.message
    if not isinstance(message_obj, Message):
        logger.warning("_refresh_and_display_subscriber_list: Message is None or inaccessible.")
        return

    page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
        session, active_bot, return_page
    )
    if total_pages == 0 or not page_subscribers_info:
        await message_obj.edit_text(_("No subscribers found."))
    else:
        new_keyboard = await create_subscriber_list_keyboard(
            translator, page_subscribers_info=page_subscribers_info, current_page=current_page, total_pages=total_pages
        )
        list_text = _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
            current_page_display=current_page + 1, total_pages=total_pages
        )
        await message_obj.edit_text(list_text, reply_markup=new_keyboard)


@subscriber_actions_router.callback_query(ViewSubscriberCallback.filter())
async def handle_view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles viewing details and actions for a specific subscriber."""
    _ = translator.gettext
    if not query.message:
        logger.warning("handle_view_subscriber called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=callback_data.telegram_id, page=callback_data.page
    )
    user_to_view = await session.get(UserSettings, callback_data.telegram_id)
    display_name = str(callback_data.telegram_id)

    active_bot = services.bot_event
    if user_to_view and user_to_view.telegram_id:
        try:
            chat_info = await active_bot.get_chat(user_to_view.telegram_id)
            display_name = format_telegram_user_display_name(chat_info)
        except TelegramAPIError:
            logger.exception("Could not fetch chat info for %s via Telegram API.", user_to_view.telegram_id)
        except Exception:
            logger.exception("Unexpected error fetching chat info for %s.", user_to_view.telegram_id)

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    if user_to_view:
        details_parts.append(
            _("Linked TT Account: {tt_username}").format(tt_username=user_to_view.teamtalk_username or _("None"))
        )
        details_parts.append(_("Language: {lang}").format(lang=user_to_view.language_code))
        noon_status = _("Enabled") if user_to_view.not_on_online_enabled else _("Disabled")
        details_parts.append(_("NOON (Not on Online): {status}").format(status=noon_status))
        notif_setting_map = {
            NotificationSetting.ALL.value: _("All (Join & Leave)"),
            NotificationSetting.LEAVE_OFF.value: _("Join Only"),
            NotificationSetting.JOIN_OFF.value: _("Leave Only"),
            NotificationSetting.NONE.value: _("None"),
        }
        notif_setting_str = user_to_view.notification_settings.value
        details_parts.append(
            _("Notifications: {setting}").format(setting=notif_setting_map.get(notif_setting_str, notif_setting_str))
        )
        mute_mode_str = _("Blacklist") if user_to_view.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        details_parts.append(_("Mute Mode: {mode}").format(mode=mute_mode_str))
    else:
        details_parts.append(_("Subscriber settings not found."))

    text = "\n".join(details_parts)
    if isinstance(query.message, Message):
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        logger.warning("handle_view_subscriber: Message is None or inaccessible.")
    await query.answer()


async def _handle_delete_subscriber_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    services: "Services",
    _tt_connection: TeamTalkConnection | None = None,
) -> None:
    """Helper to handle subscriber deletion."""
    _ = translator.gettext
    if not query.message:
        logger.warning("_handle_delete_subscriber_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    success = await user_service.delete_full_user_profile(session, target_telegram_id, services=services)
    if success:
        await query.answer(
            _("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id),
            show_alert=True,
        )
        await _refresh_and_display_subscriber_list(query, session, services, return_page, translator)
    else:
        await query.answer(
            _("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id), show_alert=True
        )


async def _handle_ban_subscriber_action(
    query: CallbackQuery,
    session: AsyncSession,
    services: "Services",
    tt_connection: TeamTalkConnection | None,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Helper to handle subscriber banning."""
    _ = translator.gettext
    if not query.message:
        logger.warning("_handle_ban_subscriber_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    # Call the service function to handle all ban and deletion logic
    _success, ban_messages = await admin_service.ban_and_delete_subscriber(
        session, services, tt_connection, target_telegram_id, translator
    )

    alert_message = " ".join(ban_messages)
    await query.answer(alert_message, show_alert=True)

    # Refresh the subscriber list UI, regardless of exact success/failure details,
    # as the state of the user (banned, deleted) has likely changed.
    await _refresh_and_display_subscriber_list(query, session, services, return_page, translator)


async def _handle_manage_tt_account_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    _services: Optional["Services"] = None,
    _tt_connection: TeamTalkConnection | None = None,
) -> None:
    """Helper to show manage TT account menu for a subscriber."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("_handle_manage_tt_account_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return
    user_settings = await session.get(UserSettings, target_telegram_id)
    current_tt_username = user_settings.teamtalk_username if user_settings else None

    keyboard = await create_manage_tt_account_keyboard(
        translator, target_telegram_id=target_telegram_id, current_tt_username=current_tt_username, page=return_page
    )
    message_text = _("Manage TeamTalk account link for subscriber {telegram_id}:").format(
        telegram_id=target_telegram_id
    )
    await query.message.edit_text(message_text, reply_markup=keyboard)
    await query.answer()


async def _handle_admin_set_language_action(
    query: CallbackQuery,
    _unused_session: AsyncSession,  # session marked as unused
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    services: Optional["Services"] = None,
    _tt_connection: TeamTalkConnection | None = None,
) -> None:
    """Helper to show language selection for a subscriber to an admin."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_SET_LANGUAGE action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    if not services:
        logger.error("Services not available in _handle_admin_set_language_action.")
        await query.answer(_("Service error. Please try again later."), show_alert=True)
        return

    available_languages = services.available_languages
    if not available_languages:
        logger.error("No available languages found in services for ADMIN_SET_LANGUAGE action.")
        await query.answer(_("Could not retrieve language list. Service misconfiguration."), show_alert=True)
        return

    lang_keyboard = await create_admin_subscriber_lang_keyboard(
        translator=translator,
        available_languages=available_languages,
        target_telegram_id=target_telegram_id,
        subscriber_page_context=return_page,
    )
    message_text = _("Select new language for subscriber {tg_id}:").format(tg_id=target_telegram_id)
    await query.message.edit_text(message_text, reply_markup=lang_keyboard)
    await query.answer()


async def _handle_admin_toggle_noon_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    services: "Services",
    _tt_connection: TeamTalkConnection | None = None,
) -> None:
    """Helper to toggle NOON for a subscriber."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_TOGGLE_NOON action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    updated_user_settings = await user_service.admin_toggle_noon_setting(session, services, target_telegram_id)

    if updated_user_settings:
        new_status_text = _("Enabled") if updated_user_settings.not_on_online_enabled else _("Disabled")
        await query.answer(
            _("NOON status for subscriber {tg_id} set to: {status}").format(
                tg_id=target_telegram_id, status=new_status_text
            ),
            show_alert=False,
        )
    else:
        await query.answer(_("Failed to toggle NOON status. Please try again."), show_alert=True)
        # If the service function returned None, it means an error occurred and UserSettings might be stale
        # or unchanged. Re-fetching or using a potentially stale object for handle_view_subscriber
        # might show incorrect info. However, handle_view_subscriber re-fetches.

    # Refresh the view for the subscriber
    await handle_view_subscriber(
        query=query,  # type: ignore
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=return_page),
        session=session,
        translator=translator,
        services=services,
    )


async def _handle_admin_set_notif_pref_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    _services: Optional["Services"] = None,
    _tt_connection: TeamTalkConnection | None = None,
) -> None:
    """Helper to show notification preference selection for a subscriber."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_SET_NOTIF_PREF action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        return
    current_notif_setting = target_user_settings.notification_settings
    notif_pref_keyboard = await create_admin_subscriber_notification_pref_keyboard(
        translator=translator,
        current_setting=current_notif_setting,
        target_telegram_id=target_telegram_id,
        subscriber_page_context=return_page,
    )
    message_text = _("Select notification preference for subscriber {tg_id}:").format(tg_id=target_telegram_id)
    await query.message.edit_text(message_text, reply_markup=notif_pref_keyboard)
    await query.answer()


async def _handle_admin_set_mute_mode_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    _services: Optional["Services"] = None,
    _tt_connection: TeamTalkConnection | None = None,
) -> None:
    """Helper to show mute mode selection for a subscriber."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_SET_MUTE_MODE action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        return
    current_mute_mode = target_user_settings.mute_list_mode
    mute_mode_keyboard = await create_admin_subscriber_mute_mode_keyboard(
        translator=translator,
        current_mode=current_mute_mode,
        target_telegram_id=target_telegram_id,
        subscriber_page_context=return_page,
    )
    message_text = _("Select mute list mode for subscriber {tg_id}:").format(tg_id=target_telegram_id)
    await query.message.edit_text(message_text, reply_markup=mute_mode_keyboard)
    await query.answer()


@subscriber_actions_router.callback_query(SubscriberActionCallback.filter())
async def handle_subscriber_action(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Dispatches subscriber-related actions by admin from the subscriber action menu."""
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    if action == SubscriberAction.DELETE:
        await _handle_delete_subscriber_action(
            query, session, target_telegram_id, return_page, translator, services, tt_connection
        )
    elif action == SubscriberAction.BAN:
        await _handle_ban_subscriber_action(
            query, session, services, tt_connection, target_telegram_id, return_page, translator
        )
    elif action == SubscriberAction.MANAGE_TT_ACCOUNT:
        await _handle_manage_tt_account_action(
            query, session, target_telegram_id, return_page, translator, services, tt_connection
        )
    elif action == SubscriberAction.ADMIN_SET_LANGUAGE:
        await _handle_admin_set_language_action(
            query, session, target_telegram_id, return_page, translator, services, tt_connection
        )
    elif action == SubscriberAction.ADMIN_TOGGLE_NOON:
        await _handle_admin_toggle_noon_action(
            query, session, target_telegram_id, return_page, translator, services, tt_connection
        )
    elif action == SubscriberAction.ADMIN_SET_NOTIF_PREF:
        await _handle_admin_set_notif_pref_action(
            query, session, target_telegram_id, return_page, translator, services, tt_connection
        )
    elif action == SubscriberAction.ADMIN_SET_MUTE_MODE:
        await _handle_admin_set_mute_mode_action(
            query, session, target_telegram_id, return_page, translator, services, tt_connection
        )
    elif action == SubscriberAction.ADMIN_VIEW_MUTE_LIST:
        await _handle_admin_view_mute_list_action(query, session, target_telegram_id, return_page, translator, services)
    else:
        await query.answer(_("Unknown action."), show_alert=True)
        logger.warning("Unknown subscriber action: %s", action)


async def _handle_admin_view_mute_list_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,  # Page of the subscriber list for back button context
    translator: gettext.GNUTranslations,
    services: "Services",
    page_num: int = 0,  # For pagination, defaults to 0 for initial call
) -> None:
    """Handles an admin viewing a specific subscriber's mute list with pagination."""
    _ = translator.gettext
    # MUTE_LIST_ITEMS_PER_PAGE is now imported at the top
    # select is now imported at the top

    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_VIEW_MUTE_LIST action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    statement = (
        select(UserSettings)
        .where(UserSettings.telegram_id == target_telegram_id)
        .options(selectinload(UserSettings.muted_users_list))  # Using getattr
    )
    result = await session.exec(statement)
    target_user_settings = result.one_or_none()

    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        await handle_view_subscriber(  # Navigate back if user not found
            query=query,
            callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=return_page),
            session=session,
            translator=translator,
            services=services,
        )
        return

    all_muted_usernames = sorted([mu.muted_teamtalk_username for mu in target_user_settings.muted_users_list])

    total_items = len(all_muted_usernames)
    total_pages = (total_items + MUTE_LIST_ITEMS_PER_PAGE - 1) // MUTE_LIST_ITEMS_PER_PAGE
    total_pages = max(total_pages, 1)  # Ensure at least 1 page even if empty

    current_page_idx = max(0, min(page_num, total_pages - 1))
    start_index = current_page_idx * MUTE_LIST_ITEMS_PER_PAGE
    end_index = start_index + MUTE_LIST_ITEMS_PER_PAGE
    usernames_on_page = all_muted_usernames[start_index:end_index]

    message_text_parts = []
    subscriber_display_name = str(target_telegram_id)
    try:
        chat_info = await services.bot_event.get_chat(target_telegram_id)
        subscriber_display_name = format_telegram_user_display_name(chat_info)
    except Exception:
        logger.warning("Could not fetch display name for %s in view_mute_list", target_telegram_id)

    message_text_parts.append(
        _("Mute list for subscriber: {subscriber_name} (ID: {subscriber_id})").format(
            subscriber_name=subscriber_display_name, subscriber_id=target_telegram_id
        )
    )
    message_text_parts.append(
        _("Mute Mode: {mode}").format(
            mode=_("Blacklist") if target_user_settings.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        )
    )

    if not all_muted_usernames:
        message_text_parts.append(_("The mute list is currently empty."))
    else:
        message_text_parts.append(
            _("Muted TeamTalk usernames (Page {current_page}/{total_pages}):").format(
                current_page=current_page_idx + 1, total_pages=total_pages
            )
        )
        for username in usernames_on_page:
            message_text_parts.append(f"- {username}")
        if not usernames_on_page and current_page_idx > 0:  # e.g. user deleted items from last page
            message_text_parts.append(_("This page is empty. Try previous pages."))

    keyboard = await create_view_mute_list_keyboard(
        translator,
        current_mute_list_page=current_page_idx,
        total_mute_list_pages=total_pages,
        target_telegram_id=target_telegram_id,
        subscriber_context_page=return_page,
    )

    final_text = "\n".join(message_text_parts)

    try:
        await query.message.edit_text(final_text, reply_markup=keyboard)
        await query.answer()
    except TelegramAPIError:
        logger.exception("Failed to edit message for viewing mute list (page %s)", current_page_idx)
        await query.answer(_("Error displaying mute list page."), show_alert=True)


@subscriber_actions_router.callback_query(PaginateMuteListCallback.filter())
async def handle_paginate_mute_list(
    query: CallbackQuery,
    callback_data: PaginateMuteListCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles pagination for the admin's view of a subscriber's mute list."""
    await _handle_admin_view_mute_list_action(
        query=query,
        session=session,
        target_telegram_id=callback_data.target_telegram_id,
        return_page=callback_data.subscriber_context_page,  # This is the page of the main subscriber list
        translator=translator,
        services=services,
        page_num=callback_data.mute_list_page,  # Pass the requested page for the mute list
    )
    await query.answer()  # Acknowledge the callback


async def _display_linkable_tt_accounts_page(
    query: CallbackQuery,
    target_telegram_id: int,
    subscriber_context_page: int,
    linkable_accounts_page_to_show: int,
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
) -> None:
    """Helper to display a paginated list of linkable TeamTalk accounts."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("_display_linkable_tt_accounts_page: Message is None or inaccessible.")
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    if not tt_connection or not tt_connection.user_accounts_cache:
        logger.warning("USER_ACCOUNTS_CACHE is empty or tt_connection not available for displaying linkable accounts.")
        await query.answer(
            _("TeamTalk server accounts cache is not populated or connection error. Please try again later."),
            show_alert=True,
        )
        session_from_bot = query.bot.get("session")  # type: ignore
        if not session_from_bot:
            logger.error("Session not found in _display_linkable_tt_accounts_page fallback.")
            if query.message:
                await query.message.edit_text(_("Error: Could not return to previous menu."))
            return

        user_settings = await session_from_bot.get(UserSettings, target_telegram_id)
        current_tt_username = user_settings.teamtalk_username if user_settings else None
        keyboard = await create_manage_tt_account_keyboard(
            translator,
            target_telegram_id=target_telegram_id,
            current_tt_username=current_tt_username,
            page=subscriber_context_page,
        )
        if query.message:
            await query.message.edit_text(
                _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
                reply_markup=keyboard,
            )
        return

    all_server_accounts: list[pytalk.UserAccount] = list(tt_connection.user_accounts_cache.values())
    if not all_server_accounts:
        await query.answer(
            _("No TeamTalk server accounts found on {server_host} or unable to fetch.").format(
                server_host=tt_connection.server_info.host
            ),
            show_alert=True,
        )
        return

    try:
        sdk_ttstr = pytalk.instance.sdk.ttstr
        all_server_accounts.sort(key=lambda acc: sdk_ttstr(acc.username).lower())
    except Exception:
        logger.exception("Error sorting server accounts. Proceeding with unsorted list.")

    items_per_page = SUBSCRIBERS_PER_PAGE
    total_linkable_pages = (len(all_server_accounts) + items_per_page - 1) // items_per_page
    total_linkable_pages = max(total_linkable_pages, 1)
    current_page_idx = max(0, min(linkable_accounts_page_to_show, total_linkable_pages - 1))
    start_idx = current_page_idx * items_per_page
    page_items_to_display = all_server_accounts[start_idx : start_idx + items_per_page]

    link_keyboard = await create_linkable_tt_account_list_keyboard(
        translator,
        page_items=page_items_to_display,
        current_page_idx=current_page_idx,
        total_pages=total_linkable_pages,
        target_telegram_id=target_telegram_id,
        subscriber_list_page=subscriber_context_page,
    )
    text_format = "Select a TeamTalk account from {server_host} to link to subscriber {telegram_id}: (Page {cur}/{tot})"
    text_content = text_format.format(
        server_host=tt_connection.server_info.host,
        telegram_id=target_telegram_id,
        cur=current_page_idx + 1,
        tot=total_linkable_pages,
    )
    if query.message:
        await query.message.edit_text(text_content, reply_markup=link_keyboard)
    await query.answer()


@subscriber_actions_router.callback_query(PaginateLinkableAccountsCallback.filter())
async def handle_paginate_linkable_accounts(
    query: CallbackQuery,
    callback_data: PaginateLinkableAccountsCallback,
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
) -> None:
    """Handles pagination for the list of linkable TeamTalk accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.subscriber_context_page,
        linkable_accounts_page_to_show=callback_data.page,
        tt_connection=tt_connection,
        translator=translator,
    )


@subscriber_actions_router.callback_query(LinkTTAccountChosenCallback.filter())
async def handle_link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles linking a chosen TeamTalk account to a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page

    if not query.message or not isinstance(query.message, Message):  # Ensure message is Message instance
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    updated_user_settings, status_key = await user_service.admin_link_tt_account(
        session, services, target_telegram_id, tt_username_to_link
    )

    alert_message = ""
    current_tt_for_keyboard = tt_username_to_link  # Optimistically assume link will succeed for keyboard

    if status_key == "linked":
        alert_message = _("TeamTalk account {new_tt_username} linked successfully.").format(
            new_tt_username=tt_username_to_link
        )
    elif status_key == "relinked":
        # We need the old username to display this message correctly.
        # The service function doesn't return it. For simplicity, we'll use a generic message here.
        # A more complex solution would involve the service returning more state or the handler fetching it.
        alert_message = _("TeamTalk account {new_tt_username} linked successfully (previous link updated).").format(
            new_tt_username=tt_username_to_link
        )
    elif status_key == "banned":
        alert_message = _("This TeamTalk username ({tt_username}) is banned and cannot be linked.").format(
            tt_username=tt_username_to_link
        )
        # If banned, keyboard shows original TT username. Fetch if needed.
        # (Service call doesn't modify passed user_settings on early "banned" return)
        user_s_for_kb = await session.get(UserSettings, target_telegram_id)
        current_tt_for_keyboard = user_s_for_kb.teamtalk_username if user_s_for_kb else None

    elif status_key == "not_found":
        alert_message = _("User settings not found for this subscriber.")
        current_tt_for_keyboard = None  # No user, no TT username
    elif status_key == "error":
        alert_message = _("Failed to link TeamTalk account. Please try again.")
        # On error, the TT username might not have changed in DB.
        user_s_for_kb = await session.get(UserSettings, target_telegram_id)  # Re-fetch to be sure
        current_tt_for_keyboard = user_s_for_kb.teamtalk_username if user_s_for_kb else None

    await query.answer(alert_message, show_alert=True)

    # Determine the TT username to display in the keyboard
    # If linking was successful, updated_user_settings will exist.
    # If not (e.g. banned, not_found, error), updated_user_settings is None.
    final_tt_username_for_keyboard = (
        updated_user_settings.teamtalk_username if updated_user_settings else current_tt_for_keyboard
    )

    updated_keyboard = await create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=final_tt_username_for_keyboard,
        page=return_page,
    )
    await query.message.edit_text(
        _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
        reply_markup=updated_keyboard,
    )


@subscriber_actions_router.callback_query(AdminSetSubscriberLanguageCallback.filter())
async def handle_admin_set_subscriber_language(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberLanguageCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles an admin setting a specific subscriber's language."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    new_lang_code = callback_data.lang_code
    subscriber_page_context = callback_data.subscriber_page_context

    updated_user_settings = await user_service.admin_set_user_language(
        session, services, target_telegram_id, new_lang_code
    )

    if updated_user_settings:
        await query.answer(
            _("Language for subscriber {tg_id} changed to {lang_code}.").format(
                tg_id=target_telegram_id, lang_code=new_lang_code
            ),
            show_alert=True,
        )
    else:
        # Check if the user was not found initially by the service, or if another error occurred.
        # The service logs details. Here, we provide generic feedback.
        # We could add a step to check if user_settings exists before calling service if we want different messages.
        await query.answer(
            _("Failed to change language. Subscriber settings might be missing or an error occurred."), show_alert=True
        )

    if query.message:  # query.message should exist if callback_data exists, but good check
        await handle_view_subscriber(
            query=query,  # type: ignore
            callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context),
            session=session,
            translator=translator,
            services=services,
        )


@subscriber_actions_router.callback_query(AdminSetSubscriberNotificationPrefCallback.filter())
async def handle_admin_set_subscriber_notification_pref(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberNotificationPrefCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles an admin setting a specific subscriber's notification preference."""
    _ = translator.gettext
    target_user_settings = await session.get(UserSettings, callback_data.target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        if query.message:
            await _refresh_and_display_subscriber_list(
                query, session, services, callback_data.subscriber_page_context, translator
            )
        return
    old_pref_val = target_user_settings.notification_settings
    new_pref_str = callback_data.setting_value
    try:
        new_pref_enum = NotificationSetting(new_pref_str)
    except ValueError:
        logger.exception("Invalid notification setting value received: %s", new_pref_str)
        await query.answer(_("Invalid setting value. Please try again."), show_alert=True)
        return
    target_user_settings.notification_settings = new_pref_enum
    try:
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        notif_setting_map = {
            NotificationSetting.ALL.value: _("All (Join & Leave)"),
            NotificationSetting.LEAVE_OFF.value: _("Join Only"),
            NotificationSetting.JOIN_OFF.value: _("Leave Only"),
            NotificationSetting.NONE.value: _("None"),
        }
        new_pref_display_name = notif_setting_map.get(new_pref_str, new_pref_str)
        await query.answer(
            _("Notification preference for subscriber {tg_id} set to: {pref}").format(
                tg_id=callback_data.target_telegram_id, pref=new_pref_display_name
            ),
            show_alert=False,
        )
    except Exception:
        logger.exception(
            "Failed to update notification preference for subscriber %s to %s",
            callback_data.target_telegram_id,
            new_pref_str,
        )
        target_user_settings.notification_settings = old_pref_val
        await query.answer(_("Failed to change notification preference. Please try again."), show_alert=True)
    if query.message:
        await handle_view_subscriber(
            query=query,
            callback_data=ViewSubscriberCallback(
                telegram_id=callback_data.target_telegram_id, page=callback_data.subscriber_page_context
            ),
            session=session,
            translator=translator,
            services=services,
        )
    return


@subscriber_actions_router.callback_query(AdminSetSubscriberMuteModeCallback.filter())
async def handle_admin_set_subscriber_mute_mode(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberMuteModeCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles an admin setting a specific subscriber's mute list mode."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    new_mode = callback_data.mode
    subscriber_page_context = callback_data.subscriber_page_context

    updated_user_settings = await user_service.admin_set_user_mute_mode(session, services, target_telegram_id, new_mode)

    if updated_user_settings:
        mode_text = _("Blacklist") if updated_user_settings.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        await query.answer(
            _("Mute list mode for subscriber {tg_id} set to: {mode}").format(tg_id=target_telegram_id, mode=mode_text),
            show_alert=False,
        )
    else:
        await query.answer(
            _("Failed to change mute mode. Subscriber settings might be missing or an error occurred."), show_alert=True
        )

    if query.message:  # query.message should exist
        await handle_view_subscriber(
            query=query,  # type: ignore
            callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context),
            session=session,
            translator=translator,
            services=services,
        )
