"""Callback query handlers for actions related to specific subscribers."""

import gettext
import logging
from typing import TYPE_CHECKING, cast

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
import pytalk
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.constants import MUTE_LIST_ITEMS_PER_PAGE
from bot.core.enums import ManageTTAccountAction, SubscriberAction
from bot.models import (
    MutedUser,
    MuteListMode,
    NotificationSetting,
    OperationResult,
    UserSettings,
)
from bot.services import admin_service, user_service
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    PaginateLinkableAccountsCallback,
    PaginateMuteListCallback,
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
    create_view_mute_list_keyboard,
)
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware
from bot.telegram_bot.ui_utils import display_paginated_list
from bot.telegram_bot.utils import format_telegram_user_display_name

from ._helpers import ensure_message_context
from .list_utils import (
    SUBSCRIBERS_PER_PAGE,
    _show_subscriber_list_page,
)

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
subscriber_actions_router = Router(name="subscriber_actions_router")
subscriber_actions_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
subscriber_actions_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())


@subscriber_actions_router.callback_query(SubscriberActionCallback.filter(F.action == SubscriberAction.DELETE))
@ensure_message_context
async def handle_delete_subscriber(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: TeamTalkConnection | None,  # Injected by middleware, unused
) -> None:
    """Handles deleting a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    # Logic from _handle_delete_subscriber_action
    success = await user_service.delete_full_user_profile(session, target_telegram_id, services=services)
    if success:
        await query.answer(
            _("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id),
            show_alert=True,
        )
        # _tt_connection was unused in the original helper, so passing tt_connection here is fine.
        await _refresh_and_display_subscriber_list(query, session, services, return_page, translator)
    else:
        await query.answer(
            _("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id), show_alert=True
        )




@subscriber_actions_router.callback_query(
    SubscriberActionCallback.filter(F.action == SubscriberAction.MANAGE_TT_ACCOUNT)
)
@ensure_message_context
async def handle_manage_tt_account(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",  # Unused in this handler
    tt_connection: TeamTalkConnection | None,  # Unused in this handler
) -> None:
    """Shows the menu to manage a subscriber's linked TeamTalk account."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page  # This is the subscriber list page

    # Logic from _handle_manage_tt_account_action
    user_settings = await session.get(UserSettings, target_telegram_id)
    current_tt_username = user_settings.teamtalk_username if user_settings else None

    keyboard = await create_manage_tt_account_keyboard(
        translator, target_telegram_id=target_telegram_id, current_tt_username=current_tt_username, page=return_page
    )
    message_text = _("Manage TeamTalk account link for subscriber {telegram_id}:").format(
        telegram_id=target_telegram_id
    )

    # @ensure_message_context guarantees query.message is a Message
    await query.message.edit_text(message_text, reply_markup=keyboard)  # type: ignore
    await query.answer()


@subscriber_actions_router.callback_query(
    SubscriberActionCallback.filter(F.action == SubscriberAction.ADMIN_SET_LANGUAGE)
)
@ensure_message_context
async def handle_admin_set_language_choice(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,  # Unused in this handler
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: TeamTalkConnection | None,  # Unused in this handler
) -> None:
    """Shows language selection menu for a subscriber to an admin."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page  # This is the subscriber list page

    # Logic from _handle_admin_set_language_action
    if not services:  # Should not happen if services are correctly injected
        logger.error("Services not available in handle_admin_set_language_choice for user %s.", query.from_user.id)
        await query.answer(_("Service error. Please try again later."), show_alert=True)
        return

    available_languages = services.available_languages
    if not available_languages:
        logger.error(
            "No available languages found in services for ADMIN_SET_LANGUAGE action by user %s.",
            query.from_user.id,
        )
        await query.answer(_("Could not retrieve language list. Service misconfiguration."), show_alert=True)
        return

    lang_keyboard = await create_admin_subscriber_lang_keyboard(
        translator=translator,
        available_languages=available_languages,
        target_telegram_id=target_telegram_id,
        subscriber_page_context=return_page,
    )
    message_text = _("Select new language for subscriber {tg_id}:").format(tg_id=target_telegram_id)

    # @ensure_message_context guarantees query.message is a Message
    await query.message.edit_text(message_text, reply_markup=lang_keyboard)  # type: ignore
    await query.answer()


@subscriber_actions_router.callback_query(
    SubscriberActionCallback.filter(F.action == SubscriberAction.ADMIN_TOGGLE_NOON)
)
@ensure_message_context
async def handle_admin_toggle_noon(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: TeamTalkConnection | None,  # Unused in this handler
) -> None:
    """Handles an admin toggling NOON setting for a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    # Logic from _handle_admin_toggle_noon_action
    updated_user_settings = await admin_service.admin_toggle_noon_setting(session, services, target_telegram_id)

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

    # Refresh the view for the subscriber
    await _display_subscriber_view(
        query=query,
        target_telegram_id=target_telegram_id,
        page_context=return_page,
        session=session,
        translator=translator,
        services=services,
    )


@subscriber_actions_router.callback_query(
    SubscriberActionCallback.filter(F.action == SubscriberAction.ADMIN_SET_NOTIF_PREF)
)
@ensure_message_context
async def handle_admin_set_notif_pref_choice(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",  # Unused in this handler
    tt_connection: TeamTalkConnection | None,  # Unused in this handler
) -> None:
    """Shows notification preference selection menu for a subscriber to an admin."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    # Logic from _handle_admin_set_notif_pref_action
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

    # @ensure_message_context guarantees query.message is a Message
    await query.message.edit_text(message_text, reply_markup=notif_pref_keyboard)  # type: ignore
    await query.answer()


@subscriber_actions_router.callback_query(
    SubscriberActionCallback.filter(F.action == SubscriberAction.ADMIN_SET_MUTE_MODE)
)
@ensure_message_context
async def handle_admin_set_mute_mode_choice(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",  # Unused in this handler
    tt_connection: TeamTalkConnection | None,  # Unused in this handler
) -> None:
    """Shows mute mode selection menu for a subscriber to an admin."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    # Logic from _handle_admin_set_mute_mode_action
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

    # @ensure_message_context guarantees query.message is a Message
    await query.message.edit_text(message_text, reply_markup=mute_mode_keyboard)  # type: ignore
    await query.answer()


@subscriber_actions_router.callback_query(
    SubscriberActionCallback.filter(F.action == SubscriberAction.ADMIN_VIEW_MUTE_LIST)
)
@ensure_message_context
async def handle_admin_view_mute_list(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    tt_connection: TeamTalkConnection | None,  # Injected by middleware, unused
) -> None:
    """Entry point for an admin to view a specific subscriber's mute list (shows page 0)."""
    await _display_subscriber_mute_list_page(
        query=query,
        session=session,
        translator=translator,
        services=services,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_list_return_page=callback_data.page,  # Page of the main subscriber list
        mute_list_page_num=0,  # Initial view of the mute list is page 0
    )


# Renamed from handle_admin_view_mute_list to be a private helper for displaying pages
async def _display_subscriber_mute_list_page(
    query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    target_telegram_id: int,
    subscriber_list_return_page: int,  # Page of the main subscriber list for "Back" button
    mute_list_page_num: int,  # Page of the mute list to display
) -> None:
    """Displays a paginated view of a subscriber's mute list."""
    _ = translator.gettext
    # Logic from _handle_admin_view_mute_list_action / new handle_admin_view_mute_list
    # 1. Fetch UserSettings with preloaded muted_users_list
    statement = (
        select(UserSettings)
        .where(UserSettings.telegram_id == target_telegram_id)
        .options(selectinload(cast(QueryableAttribute[list[MutedUser]], UserSettings.muted_users_list)))
    )
    target_user_settings = await session.scalar(statement)

    if not target_user_settings:
        await query.answer(_("Subscriber settings not found."), show_alert=True)
        logger.info("Subscriber settings not found for %s when viewing mute list.", target_telegram_id)
        return

    all_muted_usernames = sorted([mu.muted_teamtalk_username for mu in target_user_settings.muted_users_list])

    # 2. Determine subscriber display name
    subscriber_display_name = str(target_telegram_id)
    try:
        chat_info = await services.bot_event.get_chat(target_telegram_id)
        if chat_info:
            subscriber_display_name = format_telegram_user_display_name(chat_info)
    except Exception:
        logger.warning("Could not fetch display name for %s in view_mute_list", target_telegram_id, exc_info=True)

    # 3. Construct title text
    title_text_parts = [
        _("Mute list for subscriber: {subscriber_name} (ID: {subscriber_id})").format(
            subscriber_name=subscriber_display_name, subscriber_id=target_telegram_id
        ),
        _("Mute Mode: {mode}").format(
            mode=_("Blacklist") if target_user_settings.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        ),
    ]
    title_text = "\n".join(title_text_parts)
    empty_list_text = _("The mute list is currently empty.")

    # 4. Call display_paginated_list
    if query.bot is None:  # Should be guaranteed by @ensure_message_context for query.message
        logger.error("handle_admin_view_mute_list: query.bot is None. Cannot display list.")
        await query.answer(_("An error occurred: Bot instance not found."), show_alert=True)
        return

    await display_paginated_list(
        target=query,
        bot=query.bot,
        translator=translator,
        items=all_muted_usernames,
        page=mute_list_page_num,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_view_mute_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_context_page": subscriber_list_return_page,
        },
        page_size=MUTE_LIST_ITEMS_PER_PAGE,
    )
    # query.answer() is handled by display_paginated_list or its internal safe_edit_text.


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    services: "Services",
    return_page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Refreshes and displays the paginated list of subscribers by calling the central list display function."""
    _ = translator.gettext  # Add missing translator definition
    # This function is called after an action like delete/ban.
    # It should now call the refactored _show_subscriber_list_page from list_utils,
    # which handles fetching all subscribers and using display_paginated_list.

    # Ensure services.bot_event is available, as _show_subscriber_list_page needs it.
    if not services.bot_event:
        logger.error("_refresh_and_display_subscriber_list: services.bot_event is not available.")
        await query.answer(_("An internal error occurred. Please try again later."), show_alert=True)
        return

    # _show_subscriber_list_page now expects a CallbackQuery and handles the message editing.
    # It also takes the 'page' argument for which page of subscribers to show.
    await _show_subscriber_list_page(
        target=query,  # Pass the CallbackQuery
        session=session,
        bot=services.bot_event,
        translator=translator,
        page=return_page,  # The page to return to in the subscriber list
    )


async def _display_subscriber_view(
    query: CallbackQuery,
    target_telegram_id: int,
    page_context: int,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Helper function to display the subscriber details view."""
    _ = translator.gettext

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=target_telegram_id, page=page_context
    )
    user_to_view = await session.get(UserSettings, target_telegram_id)
    display_name = str(target_telegram_id)

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
    # @ensure_message_context guarantees query.message is a Message
    await cast(Message, query.message).edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await query.answer()


@subscriber_actions_router.callback_query(ViewSubscriberCallback.filter())
@ensure_message_context
async def handle_view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles viewing details and actions for a specific subscriber by calling the display helper."""
    await _display_subscriber_view(
        query=query,
        target_telegram_id=callback_data.telegram_id,
        page_context=callback_data.page,
        session=session,
        translator=translator,
        services=services,
    )


@subscriber_actions_router.callback_query(PaginateMuteListCallback.filter())
@ensure_message_context
async def handle_paginate_mute_list(
    query: CallbackQuery,
    callback_data: PaginateMuteListCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
    # tt_connection is not explicitly part of PaginateMuteListCallback's deps,
    # and _display_subscriber_mute_list_page doesn't require it.
) -> None:
    """Handles pagination for the admin's view of a subscriber's mute list."""
    # The ensure_message_context decorator handles the query.message check.
    await _display_subscriber_mute_list_page(
        query=query,
        session=session,
        translator=translator,
        services=services,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_list_return_page=callback_data.subscriber_context_page,
        mute_list_page_num=callback_data.mute_list_page,
    )
    await query.answer()  # Acknowledge the callback


@subscriber_actions_router.callback_query(ManageTTAccountCallback.filter(F.action == ManageTTAccountAction.LINK_NEW))
@ensure_message_context
async def handle_link_new_tt_account_choice(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    session: AsyncSession,  # Injected by DbSessionMiddleware
    translator: gettext.GNUTranslations,  # Injected by I18nMiddleware
    services: "Services",  # From workflow_data
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
    user_settings: UserSettings,  # Injected by UserSettingsMiddleware
) -> None:
    """Handles the 'Link/Change TeamTalk Account' action by showing a list of linkable accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.page,  # This is the page of the subscriber list
        linkable_accounts_page_to_show=0,  # Show first page of linkable accounts
        tt_connection=tt_connection,
        translator=translator,
    )
    # display_paginated_list (called by _display_linkable_tt_accounts_page) handles query.answer()


async def _display_linkable_tt_accounts_page(
    query: CallbackQuery,
    target_telegram_id: int,
    subscriber_context_page: int,
    linkable_accounts_page_to_show: int,  # This is 'page' for display_paginated_list
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
) -> None:
    """Helper to display a paginated list of linkable TeamTalk accounts using display_paginated_list."""
    _ = translator.gettext

    # query.message check is handled by the decorator on the calling handlers.
    # We assume query.message is a Message instance if this helper is reached.

    if not tt_connection or not tt_connection.is_ready or not tt_connection.user_accounts_cache:
        logger.warning(
            "TeamTalk connection not ready or USER_ACCOUNTS_CACHE is empty for displaying linkable accounts. User %s.",
            query.from_user.id,
        )
        # Fallback if TT data is unavailable.
        # Original logic tried a more complex fallback; a simple error is now used.
        await query.answer(
            _("TeamTalk server accounts are currently unavailable. Please try again later."), show_alert=True
        )
        # User can use existing navigation if available on the previous menu.
        return

    all_server_accounts: list[pytalk.UserAccount] = list(tt_connection.user_accounts_cache.values())

    try:
        sdk_ttstr = pytalk.instance.sdk.ttstr
        # Sort accounts by username, case-insensitive
        # Ensure username is converted to string for sorting if it's bytes
        all_server_accounts.sort(
            key=lambda acc: (
                sdk_ttstr(acc.username).lower()
                if isinstance(acc.username, str | bytes)  # UP038 fix
                else str(acc.username).lower()
            )
        )
    except Exception:  # Broad exception for sorting issues
        logger.exception(
            "Error sorting server accounts for user %s. Proceeding with unsorted list.", query.from_user.id
        )

    title_text = _("Select a TeamTalk account from {server_host} to link to subscriber {telegram_id}:").format(
        server_host=tt_connection.server_info.host, telegram_id=target_telegram_id
    )
    empty_list_text = _("No TeamTalk server accounts found on {server_host}.").format(
        server_host=tt_connection.server_info.host
    )
    if not all_server_accounts:  # Override empty text if cache was initially there but yielded no accounts
        empty_list_text = _("No TeamTalk server accounts found on {server_host} or unable to fetch.").format(
            server_host=tt_connection.server_info.host
        )
    if query.bot is None:
        logger.error("_display_linkable_tt_accounts_page: query.bot is None. Cannot display list.")
        await query.answer(_("An error occurred while displaying the list. Bot instance not found."), show_alert=True)
        return

    await display_paginated_list(
        target=query,  # Changed to target
        bot=query.bot,
        translator=translator,
        items=all_server_accounts,
        page=linkable_accounts_page_to_show,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_linkable_tt_account_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_list_page": subscriber_context_page,  # For "Back" button context
        },
        page_size=SUBSCRIBERS_PER_PAGE,  # SUBSCRIBERS_PER_PAGE is imported.
        server_host_for_display=None,  # Server host is already in title_text
    )
    # query.answer() is handled by display_paginated_list or safe_edit_text


@subscriber_actions_router.callback_query(PaginateLinkableAccountsCallback.filter())
@ensure_message_context
async def handle_paginate_linkable_accounts(
    query: CallbackQuery,
    callback_data: PaginateLinkableAccountsCallback,
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
) -> None:
    """Handles pagination for the list of linkable TeamTalk accounts."""
    # The ensure_message_context decorator handles the query.message check.
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.subscriber_context_page,
        linkable_accounts_page_to_show=callback_data.page,
        tt_connection=tt_connection,
        translator=translator,
    )


@subscriber_actions_router.callback_query(LinkTTAccountChosenCallback.filter())
@ensure_message_context
async def handle_link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles linking a chosen TeamTalk account to a subscriber."""
    _ = translator.gettext
    # The ensure_message_context decorator handles the query.message check.
    # We assume query.message is a Message instance if this handler is reached.
    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page

    operation_result: OperationResult = await admin_service.admin_link_tt_account(
        session, services, target_telegram_id, tt_username_to_link
    )

    alert_message_args = operation_result.message_args or {}
    # Ensure all required args for specific keys are present, or provide defaults
    if "tt_username" not in alert_message_args:  # For banned message
        alert_message_args["tt_username"] = tt_username_to_link
    if "new_tt_username" not in alert_message_args:  # For success messages
        alert_message_args["new_tt_username"] = tt_username_to_link

    alert_message = _(operation_result.message_key).format(**alert_message_args)
    await query.answer(alert_message, show_alert=True)

    # Determine the TT username to display in the keyboard for UI refresh
    # If operation was successful and returned user_settings, use that.
    # Otherwise, fetch current settings to display the potentially unchanged TT username.
    final_tt_username_for_keyboard: str | None
    if operation_result.success and operation_result.user_settings:
        final_tt_username_for_keyboard = operation_result.user_settings.teamtalk_username
    else:
        # Fetch current settings as the operation might have failed or not returned settings
        user_s_for_kb = await session.get(UserSettings, target_telegram_id)
        final_tt_username_for_keyboard = user_s_for_kb.teamtalk_username if user_s_for_kb else None
        # If user_s_for_kb is None (e.g. "not_found" case), final_tt_username_for_keyboard will be None

    updated_keyboard = await create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=final_tt_username_for_keyboard,  # Use the determined username
        page=return_page,
    )
    # @ensure_message_context guarantees query.message is a Message
    # so, the isinstance check and the else branch are redundant.
    await cast(Message, query.message).edit_text(
        _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
        reply_markup=updated_keyboard,
    )


@subscriber_actions_router.callback_query(AdminSetSubscriberLanguageCallback.filter())
@ensure_message_context
async def handle_admin_set_subscriber_language(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberLanguageCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles an admin setting a specific subscriber's language."""
    _ = translator.gettext
    # The ensure_message_context decorator handles the query.message check.
    target_telegram_id = callback_data.target_telegram_id
    new_lang_code = callback_data.lang_code
    subscriber_page_context = callback_data.subscriber_page_context

    updated_user_settings = await admin_service.admin_set_user_language(
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

    # query.message is guaranteed to exist here due to the @ensure_message_context decorator.
    await handle_view_subscriber(
        query=query,
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context),
        session=session,
        translator=translator,
        services=services,
    )


@subscriber_actions_router.callback_query(AdminSetSubscriberNotificationPrefCallback.filter())
@ensure_message_context
async def handle_admin_set_subscriber_notification_pref(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberNotificationPrefCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles an admin setting a specific subscriber's notification preference using the service layer."""
    _ = translator.gettext
    # The ensure_message_context decorator handles the query.message check.
    target_telegram_id = callback_data.target_telegram_id
    new_pref_str = callback_data.setting_value
    subscriber_page_context = callback_data.subscriber_page_context

    try:
        new_pref_enum = NotificationSetting(new_pref_str)
    except ValueError:
        logger.exception(
            "Invalid notification setting value received: %s for user %s", new_pref_str, target_telegram_id
        )
        await query.answer(_("Invalid setting value. Please try again."), show_alert=True)
        return

    updated_user_settings = await admin_service.admin_set_user_notification_preference(
        session, services, target_telegram_id, new_pref_enum
    )

    if updated_user_settings:
        notif_setting_map = {
            NotificationSetting.ALL.value: _("All (Join & Leave)"),
            NotificationSetting.LEAVE_OFF.value: _("Join Only"),
            NotificationSetting.JOIN_OFF.value: _("Leave Only"),
            NotificationSetting.NONE.value: _("None"),
        }
        # Use the value from the updated_user_settings which is confirmed from DB
        new_pref_display_name = notif_setting_map.get(
            updated_user_settings.notification_settings.value, updated_user_settings.notification_settings.value
        )
        await query.answer(
            _("Notification preference for subscriber {tg_id} set to: {pref}").format(
                tg_id=target_telegram_id, pref=new_pref_display_name
            ),
            show_alert=False,
        )
    else:
        # Service function handles logging of specific error (e.g., user not found, DB error)
        msg = _(
            "Failed to change notification preference for subscriber {tg_id}. Please check logs or try again."
        ).format(tg_id=target_telegram_id)
        await query.answer(msg, show_alert=True)

    # Refresh the main subscriber view to show updated details
    # query.message is guaranteed to exist here due to @ensure_message_context.
    await handle_view_subscriber(
        query=query,
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context),
        session=session,
        translator=translator,
        services=services,
    )
    # No explicit return needed as it's the end of the function


@subscriber_actions_router.callback_query(AdminSetSubscriberMuteModeCallback.filter())
@ensure_message_context
async def handle_admin_set_subscriber_mute_mode(
    query: CallbackQuery,
    callback_data: AdminSetSubscriberMuteModeCallback,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles an admin setting a specific subscriber's mute list mode."""
    _ = translator.gettext
    # The ensure_message_context decorator handles the query.message check.
    target_telegram_id = callback_data.target_telegram_id
    new_mode = callback_data.mode
    subscriber_page_context = callback_data.subscriber_page_context

    updated_user_settings = await admin_service.admin_set_user_mute_mode(
        session, services, target_telegram_id, new_mode
    )

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

    # query.message is guaranteed to exist here.
    await handle_view_subscriber(
        query=query,
        callback_data=ViewSubscriberCallback(telegram_id=target_telegram_id, page=subscriber_page_context),
        session=session,
        translator=translator,
        services=services,
    )
