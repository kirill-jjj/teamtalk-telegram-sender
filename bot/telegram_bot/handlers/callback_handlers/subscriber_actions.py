"""Callback query handlers for actions related to specific subscribers."""

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

import pytalk
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import ManageTTAccountAction, SubscriberAction
from bot.database import crud
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.services import user_service
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    PaginateLinkableAccountsCallback,
    SubscriberActionCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.keyboards import (
    create_admin_subscriber_lang_keyboard,
    create_admin_subscriber_mute_mode_keyboard,
    create_admin_subscriber_notification_pref_keyboard,
    create_linkable_tt_account_list_keyboard,
    create_manage_tt_account_keyboard,
    create_subscriber_action_menu_keyboard,
    create_subscriber_list_keyboard,
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
        except Exception: # noqa: BLE001
            logger.exception("Unexpected error fetching chat info for %s.", user_to_view.telegram_id)

    details_parts = [f"<b>{_('Subscriber')}: {display_name}</b>"]
    if user_to_view:
        details_parts.append(
            _("Linked TT Account: {tt_username}").format(
                tt_username=user_to_view.teamtalk_username or _("None")
            )
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
        notif_setting_str = user_to_view.notification_settings.value # Corrected: notification_settings
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
    query: CallbackQuery, session: AsyncSession, target_telegram_id: int,
    return_page: int, translator: gettext.GNUTranslations, services: "Services"
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
    query: CallbackQuery, session: AsyncSession, services: "Services",
    tt_connection: TeamTalkConnection | None, target_telegram_id: int,
    return_page: int, translator: gettext.GNUTranslations
) -> None:
    """Helper to handle subscriber banning."""
    _ = translator.gettext
    if not query.message:
        logger.warning("_handle_ban_subscriber_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    user_settings = await session.get(UserSettings, target_telegram_id)
    tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

    banned_tg = await crud.add_to_ban_list(
        session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu"
    )
    banned_tt = False
    if tt_username_to_ban:
        banned_tt = await crud.add_to_ban_list(
            session, teamtalk_username=tt_username_to_ban,
            reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
        )
        if tt_connection and tt_connection.instance:
            try:
                logger.info(
                    "Conceptual TeamTalk server ban for %s on %s (not implemented in this step)",
                    tt_username_to_ban, tt_connection.server_info.host)
            except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):
                logger.exception("Error during conceptual TeamTalk ban for %s on %s.",
                                 tt_username_to_ban, tt_connection.server_info.host)
            except Exception: # noqa: BLE001
                logger.exception("Unexpected error during conceptual TeamTalk ban for %s on %s.",
                                 tt_username_to_ban, tt_connection.server_info.host)
        else:
            logger.warning(
                "Skipping conceptual TeamTalk ban for %s as tt_connection or instance is None/invalid.",
                tt_username_to_ban,
            )

    await user_service.delete_full_user_profile(session, target_telegram_id, services=services)
    ban_messages = []
    if banned_tg:
        ban_messages.append(_("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id))
    if tt_username_to_ban and banned_tt:
        ban_messages.append(_("TeamTalk username {tt_username} banned.").format(tt_username=tt_username_to_ban))
    alert_message = " ".join(ban_messages)
    alert_message = _("{ban_report} Subscriber data also deleted.").format(ban_report=alert_message) if alert_message \
        else _("User already banned or error occurred.")
    await query.answer(alert_message, show_alert=True)
    await _refresh_and_display_subscriber_list(query, session, services, return_page, translator)

async def _handle_manage_tt_account_action(
    query: CallbackQuery, current_session: AsyncSession, target_telegram_id: int,
    return_page: int, translator: gettext.GNUTranslations
) -> None:
    """Helper to show manage TT account menu for a subscriber."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("_handle_manage_tt_account_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return
    user_settings = await current_session.get(UserSettings, target_telegram_id)
    current_tt_username = user_settings.teamtalk_username if user_settings else None

    keyboard = await create_manage_tt_account_keyboard(
        translator, target_telegram_id=target_telegram_id,
        current_tt_username=current_tt_username, page=return_page
    )
    await query.message.edit_text(
        _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
        reply_markup=keyboard,
    )
    await query.answer()

async def _handle_admin_set_language_action(
    query: CallbackQuery, _session: AsyncSession, # session marked as unused
    target_telegram_id: int, return_page: int, translator: gettext.GNUTranslations
) -> None:
    """Helper to show language selection for a subscriber to an admin."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_SET_LANGUAGE action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    if hasattr(translator, 'language_data_provider') and \
       hasattr(translator.language_data_provider, 'get_available_locales_info'):
        available_languages = translator.language_data_provider.get_available_locales_info()
    else:
        logger.error("Language data provider not found on translator for ADMIN_SET_LANGUAGE action.")
        await query.answer(_("Could not retrieve language list. Please try again later."), show_alert=True)
        return

    lang_keyboard = await create_admin_subscriber_lang_keyboard(
        translator=translator, available_languages=available_languages,
        target_telegram_id=target_telegram_id, subscriber_page_context=return_page
    )
    await query.message.edit_text(
        _("Select new language for subscriber {tg_id}:").format(tg_id=target_telegram_id),
        reply_markup=lang_keyboard
    )
    await query.answer()

async def _handle_admin_toggle_noon_action(
    query: CallbackQuery, session: AsyncSession, target_telegram_id: int,
    return_page: int, translator: gettext.GNUTranslations, services: "Services"
) -> None:
    """Helper to toggle NOON for a subscriber."""
    _ = translator.gettext
    if not query.message or not isinstance(query.message, Message):
        logger.warning("ADMIN_TOGGLE_NOON action called without message context.")
        await query.answer(_("An error occurred."), show_alert=True)
        return

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        return

    old_status = target_user_settings.not_on_online_enabled
    target_user_settings.not_on_online_enabled = not old_status
    if target_user_settings.not_on_online_enabled:
        target_user_settings.not_on_online_confirmed = True
    try:
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        new_status_text = _("Enabled") if target_user_settings.not_on_online_enabled else _("Disabled")
        await query.answer(
            _("NOON status for subscriber {tg_id} set to: {status}").format(
                tg_id=target_telegram_id, status=new_status_text), show_alert=False)
    except Exception:
        logger.exception("Failed to toggle NOON for subscriber %s", target_telegram_id)
        target_user_settings.not_on_online_enabled = old_status
        if target_user_settings.not_on_online_enabled and not old_status:
             target_user_settings.not_on_online_confirmed = False
        await query.answer(_("Failed to toggle NOON status. Please try again."), show_alert=True)

    await handle_view_subscriber(
        query=query,
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=return_page),
        session=session, translator=translator, services=services)

async def _handle_admin_set_notif_pref_action(
    query: CallbackQuery, session: AsyncSession, target_telegram_id: int,
    return_page: int, translator: gettext.GNUTranslations
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
    current_notif_setting = target_user_settings.notification_settings # Corrected
    notif_pref_keyboard = await create_admin_subscriber_notification_pref_keyboard(
        translator=translator, current_setting=current_notif_setting,
        target_telegram_id=target_telegram_id, subscriber_page_context=return_page)
    await query.message.edit_text(
        _("Select notification preference for subscriber {tg_id}:").format(tg_id=target_telegram_id),
        reply_markup=notif_pref_keyboard)
    await query.answer()

async def _handle_admin_set_mute_mode_action(
    query: CallbackQuery, session: AsyncSession, target_telegram_id: int,
    return_page: int, translator: gettext.GNUTranslations
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
        translator=translator, current_mode=current_mute_mode,
        target_telegram_id=target_telegram_id, subscriber_page_context=return_page)
    await query.message.edit_text(
        _("Select mute list mode for subscriber {tg_id}:").format(tg_id=target_telegram_id),
        reply_markup=mute_mode_keyboard)
    await query.answer()

@subscriber_actions_router.callback_query(SubscriberActionCallback.filter())
async def handle_subscriber_action(
    query: CallbackQuery, callback_data: SubscriberActionCallback, session: AsyncSession,
    tt_connection: TeamTalkConnection | None, translator: gettext.GNUTranslations, services: "Services"
) -> None:
    """
    Dispatches subscriber-related actions triggered by admin from the subscriber action menu.
    """
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    action_handlers_map = {
        SubscriberAction.DELETE: _handle_delete_subscriber_action,
        SubscriberAction.BAN: _handle_ban_subscriber_action,
        SubscriberAction.MANAGE_TT_ACCOUNT: _handle_manage_tt_account_action,
        SubscriberAction.ADMIN_SET_LANGUAGE: _handle_admin_set_language_action,
        SubscriberAction.ADMIN_TOGGLE_NOON: _handle_admin_toggle_noon_action,
        SubscriberAction.ADMIN_SET_NOTIF_PREF: _handle_admin_set_notif_pref_action,
        SubscriberAction.ADMIN_SET_MUTE_MODE: _handle_admin_set_mute_mode_action,
    }

    handler_func = action_handlers_map.get(action)

    if handler_func:
        kwargs_for_handler = {
            "query": query, "session": session, "target_telegram_id": target_telegram_id,
            "return_page": return_page, "translator": translator
        }
        if action in {SubscriberAction.DELETE, SubscriberAction.BAN, SubscriberAction.ADMIN_TOGGLE_NOON}:
            kwargs_for_handler["services"] = services
        if action == SubscriberAction.BAN:
            kwargs_for_handler["tt_connection"] = tt_connection

        if action == SubscriberAction.ADMIN_SET_LANGUAGE:
             kwargs_for_handler.pop("session", None)

        await handler_func(**kwargs_for_handler) # type: ignore
    else:
        await query.answer(_("Unknown action."), show_alert=True)
        logger.warning("Unknown subscriber action: %s", action)


async def _display_linkable_tt_accounts_page(
    query: CallbackQuery, target_telegram_id: int, subscriber_context_page: int,
    linkable_accounts_page_to_show: int, tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations
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
        session_from_bot = query.bot.get("session") # type: ignore
        if not session_from_bot:
            logger.error("Session not found in _display_linkable_tt_accounts_page fallback.")
            if query.message:
                await query.message.edit_text(_("Error: Could not return to previous menu."))
            return

        user_settings = await session_from_bot.get(UserSettings, target_telegram_id)
        current_tt_username = user_settings.teamtalk_username if user_settings else None
        keyboard = await create_manage_tt_account_keyboard(
            translator, target_telegram_id=target_telegram_id,
            current_tt_username=current_tt_username, page=subscriber_context_page
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
                server_host=tt_connection.server_info.host), show_alert=True)
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
    page_items_to_display = all_server_accounts[start_idx:start_idx + items_per_page]

    link_keyboard = await create_linkable_tt_account_list_keyboard(
        translator, page_items=page_items_to_display, current_page_idx=current_page_idx,
        total_pages=total_linkable_pages, target_telegram_id=target_telegram_id,
        subscriber_list_page=subscriber_context_page,
    )
    text_format = (
        "Select a TeamTalk account from {server_host} to link to subscriber {telegram_id}: "
        "(Page {cur}/{tot})"
    )
    text_content = text_format.format(
        server_host=tt_connection.server_info.host, telegram_id=target_telegram_id,
        cur=current_page_idx + 1, tot=total_linkable_pages,
    )
    if query.message:
        await query.message.edit_text(text_content, reply_markup=link_keyboard)
    await query.answer()

@subscriber_actions_router.callback_query(PaginateLinkableAccountsCallback.filter())
async def handle_paginate_linkable_accounts(
    query: CallbackQuery, callback_data: PaginateLinkableAccountsCallback,
    tt_connection: TeamTalkConnection | None, translator: gettext.GNUTranslations,
) -> None:
    """Handles pagination for the list of linkable TeamTalk accounts."""
    await _display_linkable_tt_accounts_page(
        query=query, target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.subscriber_context_page,
        linkable_accounts_page_to_show=callback_data.page,
        tt_connection=tt_connection, translator=translator,
    )

@subscriber_actions_router.callback_query(LinkTTAccountChosenCallback.filter())
async def handle_link_tt_account_chosen(
    query: CallbackQuery, callback_data: LinkTTAccountChosenCallback, session: AsyncSession,
    translator: gettext.GNUTranslations, services: "Services",
) -> None:
    """Handles linking a chosen TeamTalk account to a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page

    if not query.message:
        await query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        await query.answer(
            _("This TeamTalk username ({tt_username}) is banned and cannot be linked.").format(
                tt_username=tt_username_to_link), show_alert=True)
        user_s = await session.get(UserSettings, target_telegram_id)
        current_tt_username = user_s.teamtalk_username if user_s else None
        kb = await create_manage_tt_account_keyboard(
            translator, target_telegram_id, current_tt_username, return_page)
        if isinstance(query.message, Message):
            await query.message.edit_text(
                _("Manage TeamTalk account link for subscriber {telegram_id}:").format(
                    telegram_id=target_telegram_id), reply_markup=kb)
        return

    target_user_settings = await session.get(UserSettings, target_telegram_id)
    if not target_user_settings:
        await query.answer(_("User settings not found for this subscriber."), show_alert=True)
        return

    old_tt_username = target_user_settings.teamtalk_username
    target_user_settings.teamtalk_username = tt_username_to_link
    target_user_settings.not_on_online_confirmed = True
    try:
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        alert_text_parts = [
            _("TeamTalk account {new_tt_username} linked successfully.").format(new_tt_username=tt_username_to_link)]
        if old_tt_username and old_tt_username != tt_username_to_link:
            alert_text_parts.append(_("(Replaced {old_tt_username})").format(old_tt_username=old_tt_username))
        await query.answer(" ".join(alert_text_parts), show_alert=True)
    except Exception:
        logger.exception("Failed to link TeamTalk account %s for subscriber %s",
                         tt_username_to_link, target_telegram_id)
        target_user_settings.teamtalk_username = old_tt_username
        await query.answer(_("Failed to link TeamTalk account. Please try again."), show_alert=True)

    if isinstance(query.message, Message):
        updated_keyboard = await create_manage_tt_account_keyboard(
            translator, target_telegram_id=target_telegram_id,
            current_tt_username=target_user_settings.teamtalk_username, page=return_page)
        await query.message.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=updated_keyboard)

@subscriber_actions_router.callback_query(AdminSetSubscriberLanguageCallback.filter())
async def handle_admin_set_subscriber_language(
    query: CallbackQuery, callback_data: AdminSetSubscriberLanguageCallback, session: AsyncSession,
    translator: gettext.GNUTranslations, services: "Services"
) -> None:
    """Handles an admin setting a specific subscriber's language."""
    _ = translator.gettext
    target_user_settings = await session.get(UserSettings, callback_data.target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        if query.message:
            await _refresh_and_display_subscriber_list(
                query, session, services, callback_data.subscriber_page_context, translator)
        return
    old_lang = target_user_settings.language_code
    new_lang_code = callback_data.lang_code
    target_user_settings.language_code = new_lang_code
    try:
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        await query.answer(
            _("Language for subscriber {tg_id} changed to {lang_code}.").format(
                tg_id=callback_data.target_telegram_id, lang_code=new_lang_code),
            show_alert=True)
    except Exception:
        logger.exception("Failed to update language for subscriber %s to %s",
                         callback_data.target_telegram_id, new_lang_code)
        target_user_settings.language_code = old_lang
        await query.answer(_("Failed to change language. Please try again."), show_alert=True)
    if query.message:
        await handle_view_subscriber(
            query=query,
            callback_data=ViewSubscriberCallback(
                telegram_id=callback_data.target_telegram_id, page=callback_data.subscriber_page_context),
            session=session, translator=translator, services=services)

@subscriber_actions_router.callback_query(AdminSetSubscriberNotificationPrefCallback.filter())
async def handle_admin_set_subscriber_notification_pref(
    query: CallbackQuery, callback_data: AdminSetSubscriberNotificationPrefCallback, session: AsyncSession,
    translator: gettext.GNUTranslations, services: "Services"
) -> None:
    """Handles an admin setting a specific subscriber's notification preference."""
    _ = translator.gettext
    target_user_settings = await session.get(UserSettings, callback_data.target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        if query.message:
            await _refresh_and_display_subscriber_list(
                query, session, services, callback_data.subscriber_page_context, translator)
        return
    old_pref_val = target_user_settings.notification_settings # Corrected
    new_pref_str = callback_data.setting_value
    try:
        new_pref_enum = NotificationSetting(new_pref_str)
    except ValueError:
        logger.exception("Invalid notification setting value received: %s", new_pref_str)
        await query.answer(_("Invalid setting value. Please try again."), show_alert=True)
        return
    target_user_settings.notification_settings = new_pref_enum # Corrected
    try:
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        notif_setting_map = {
            NotificationSetting.ALL.value: _("All (Join & Leave)"),
            NotificationSetting.LEAVE_OFF.value: _("Join Only"),
            NotificationSetting.JOIN_OFF.value: _("Leave Only"),
            NotificationSetting.NONE.value: _("None")}
        new_pref_display_name = notif_setting_map.get(new_pref_str, new_pref_str)
        await query.answer(
            _("Notification preference for subscriber {tg_id} set to: {pref}").format(
                tg_id=callback_data.target_telegram_id, pref=new_pref_display_name),
            show_alert=False)
    except Exception:
        logger.exception("Failed to update notification preference for subscriber %s to %s",
                         callback_data.target_telegram_id, new_pref_str)
        target_user_settings.notification_settings = old_pref_val # Corrected
        await query.answer(_("Failed to change notification preference. Please try again."), show_alert=True)
    if query.message:
        await handle_view_subscriber(
            query=query,
            callback_data=ViewSubscriberCallback(
                telegram_id=callback_data.target_telegram_id, page=callback_data.subscriber_page_context),
            session=session, translator=translator, services=services)

@subscriber_actions_router.callback_query(AdminSetSubscriberMuteModeCallback.filter())
async def handle_admin_set_subscriber_mute_mode(
    query: CallbackQuery, callback_data: AdminSetSubscriberMuteModeCallback, session: AsyncSession,
    translator: gettext.GNUTranslations, services: "Services"
) -> None:
    """Handles an admin setting a specific subscriber's mute list mode."""
    _ = translator.gettext
    target_user_settings = await session.get(UserSettings, callback_data.target_telegram_id)
    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        if query.message:
            await _refresh_and_display_subscriber_list(
                query, session, services, callback_data.subscriber_page_context, translator)
        return
    old_mode = target_user_settings.mute_list_mode
    new_mode = callback_data.mode
    target_user_settings.mute_list_mode = new_mode
    try:
        await session.commit()
        await session.refresh(target_user_settings)
        services.cache.update_user_settings(target_user_settings)
        mode_text = _("Blacklist") if new_mode == MuteListMode.blacklist else _("Whitelist")
        await query.answer(
            _("Mute list mode for subscriber {tg_id} set to: {mode}").format(
                tg_id=callback_data.target_telegram_id, mode=mode_text),
            show_alert=False)
    except Exception:
        logger.exception("Failed to update mute mode for subscriber %s to %s",
                         callback_data.target_telegram_id, new_mode.value)
        target_user_settings.mute_list_mode = old_mode
        await query.answer(_("Failed to change mute mode. Please try again."), show_alert=True)
    if query.message:
        await handle_view_subscriber(
            query=query,
            callback_data=ViewSubscriberCallback(
                telegram_id=callback_data.target_telegram_id, page=callback_data.subscriber_page_context),
            session=session, translator=translator, services=services)
