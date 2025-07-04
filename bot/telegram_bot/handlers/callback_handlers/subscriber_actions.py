import logging
from aiogram import Router, F, Bot as AiogramBot # Renamed Bot
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
# from pytalk.instance import TeamTalkInstance # Will use tt_connection.instance
from bot.teamtalk_bot.connection import TeamTalkConnection # For type hinting

from bot.telegram_bot.callback_data import (
    ViewSubscriberCallback,
    SubscriberActionCallback,
    ManageTTAccountCallback,
    LinkTTAccountChosenCallback,
    SubscriberListCallback
)
from bot.telegram_bot.keyboards import (
    create_subscriber_action_menu_keyboard,
    create_manage_tt_account_keyboard,
    create_linkable_tt_account_list_keyboard,
    create_subscriber_list_keyboard
)
from bot.models import UserSettings, BanList
from bot.database import crud
from bot.services import user_service
# from bot.state import ADMIN_IDS_CACHE, USER_ACCOUNTS_CACHE # Will use app/tt_connection caches
from bot.core.enums import SubscriberListAction, SubscriberAction, ManageTTAccountAction
from bot.telegram_bot.middlewares import TeamTalkConnectionCheckMiddleware # Corrected middleware
import pytalk
from .list_utils import _get_paginated_subscribers_info
from bot.telegram_bot.utils import format_telegram_user_display_name

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
subscriber_actions_router = Router(name="subscriber_actions_router")
subscriber_actions_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    bot: AiogramBot, # Use aliased Bot
    return_page: int,
    _: callable,
    app: "Application" # Pass app if needed by underlying functions like _get_paginated_subscribers_info
):
    if not query.message:
        logger.warning("_refresh_and_display_subscriber_list called with no message context.")
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    # _get_paginated_subscribers_info now takes app if it needs app.subscribed_users_cache
    # For now, it uses crud.get_all_subscribers_ids(session)
    page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
        session, bot, return_page # Pass app if _get_paginated_subscribers_info is changed
    )
    if total_pages == 0 or not page_subscribers_info:
        await query.message.edit_text(_("No subscribers found."))
    else:
        new_keyboard = create_subscriber_list_keyboard(
            _, page_subscribers_info=page_subscribers_info, current_page=current_page, total_pages=total_pages
        )
        await query.message.edit_text(
            _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                current_page_display=current_page + 1, total_pages=total_pages
            ),
            reply_markup=new_keyboard
        )

# Removed F.from_user.id.in_(ADMIN_IDS_CACHE) from router filter, will check in handler
@subscriber_actions_router.callback_query(ViewSubscriberCallback.filter())
async def handle_view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    session: AsyncSession,
    _: callable,
    app: "Application" # Inject app
):
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    keyboard = create_subscriber_action_menu_keyboard(
        _,
        target_telegram_id=callback_data.telegram_id,
        page=callback_data.page
    )
    user_to_view = await session.get(UserSettings, callback_data.telegram_id)
    display_name = str(callback_data.telegram_id)

    # Use app's bot instance for get_chat
    active_bot = app.tg_bot_event
    if user_to_view and user_to_view.telegram_id:
        try:
            chat_info = await active_bot.get_chat(user_to_view.telegram_id)
            display_name = format_telegram_user_display_name(chat_info)
        except TelegramAPIError as e_tg:
            logger.error(f"Could not fetch chat info for {user_to_view.telegram_id} via Telegram API: {e_tg}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error fetching chat info for {user_to_view.telegram_id}: {e}", exc_info=True)

    text = _("Actions for subscriber: {display_name}").format(display_name=display_name)
    if user_to_view and user_to_view.teamtalk_username:
        text += _("\nLinked TeamTalk account: {tt_username}").format(tt_username=user_to_view.teamtalk_username)

    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()


# Removed F.from_user.id.in_(ADMIN_IDS_CACHE)
@subscriber_actions_router.callback_query(SubscriberActionCallback.filter())
async def handle_subscriber_action(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    bot: AiogramBot, # This is app.tg_bot_event or app.tg_bot_message
    tt_connection: TeamTalkConnection | None, # From middleware, checked by TeamTalkConnectionCheckMiddleware
    _: callable,
    app: "Application" # Inject app
):
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    if action == SubscriberAction.DELETE:
        # user_service.delete_full_user_profile might need app if it updates app-level caches
        success = await user_service.delete_full_user_profile(session, target_telegram_id, app=app)
        if success:
            await query.answer(_("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id), show_alert=True)
            await _refresh_and_display_subscriber_list(query, session, bot, return_page, _, app)
        else:
            await query.answer(_("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id), show_alert=True)
        return

    elif action == SubscriberAction.BAN:
        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

        banned_tg = await crud.add_to_ban_list(session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu")
        banned_tt = False
        if tt_username_to_ban:
            banned_tt = await crud.add_to_ban_list(session, teamtalk_username=tt_username_to_ban, reason=f"Banned by admin (linked to TG ID: {target_telegram_id})")
            if tt_connection and tt_connection.instance : # tt_connection should be valid due to router middleware
                try:
                    # Conceptual: Actual TT server ban would happen here using tt_connection.instance
                    logger.info(f"Conceptual TeamTalk server ban for {tt_username_to_ban} on {tt_connection.server_info.host} (not implemented in this step)")
                except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError) as e_tt:
                    logger.error(f"Error during conceptual TeamTalk ban for {tt_username_to_ban} on {tt_connection.server_info.host}: {e_tt}", exc_info=True)
                except Exception as e:
                    logger.error(f"Unexpected error during conceptual TeamTalk ban for {tt_username_to_ban} on {tt_connection.server_info.host}: {e}", exc_info=True)
            else:
                logger.warning(f"Skipping conceptual TeamTalk ban for {tt_username_to_ban} as tt_connection or its instance is None/invalid.")

        await user_service.delete_full_user_profile(session, target_telegram_id, app=app) # Pass app

        ban_messages = []
        if banned_tg: ban_messages.append(_("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id))
        if tt_username_to_ban and banned_tt: ban_messages.append(_("TeamTalk username {tt_username} banned.").format(tt_username=tt_username_to_ban))

        alert_message = " ".join(ban_messages) if ban_messages else _("User already banned or error occurred.")
        if ban_messages: alert_message += " " + _("Subscriber data also deleted.")

        await query.answer(alert_message, show_alert=True)
        await _refresh_and_display_subscriber_list(query, session, bot, return_page, _, app)
        return

    elif action == SubscriberAction.MANAGE_TT_ACCOUNT:
        user_settings = await session.get(UserSettings, target_telegram_id)
        current_tt_username = user_settings.teamtalk_username if user_settings else None
        keyboard = create_manage_tt_account_keyboard(_, target_telegram_id=target_telegram_id, current_tt_username=current_tt_username, page=return_page)
        await query.message.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=keyboard
        )
        await query.answer()
        return

    else:
        await query.answer(_("Unknown action."), show_alert=True)
        logger.warning(f"Unknown subscriber action: {action}")


# Removed F.from_user.id.in_(ADMIN_IDS_CACHE)
@subscriber_actions_router.callback_query(ManageTTAccountCallback.filter())
async def handle_manage_tt_account(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    session: AsyncSession,
    tt_connection: TeamTalkConnection | None, # From middleware
    _: callable,
    app: "Application" # Inject app
):
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    user_settings = await session.get(UserSettings, target_telegram_id)
    if not user_settings:
        await query.answer(_("User settings not found for this subscriber."), show_alert=True)
        return

    if action == ManageTTAccountAction.UNLINK:
        if user_settings.teamtalk_username:
            unlinked_tt_username = user_settings.teamtalk_username
            user_settings.teamtalk_username = None
            user_settings.not_on_online_confirmed = False
            await session.commit()
            await session.refresh(user_settings)
            # Update global USER_SETTINGS_CACHE. If app-managed, use app.user_settings_cache
            app.user_settings_cache[user_settings.telegram_id] = user_settings
            await query.answer(_("TeamTalk account {tt_username} unlinked.").format(tt_username=unlinked_tt_username), show_alert=True)
        else:
            await query.answer(_("No TeamTalk account was linked."), show_alert=True)

        keyboard = create_manage_tt_account_keyboard(_, target_telegram_id=target_telegram_id, current_tt_username=None, page=return_page)
        await query.message.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=keyboard
        )
        return

    elif action == ManageTTAccountAction.LINK_NEW:
        if not tt_connection or not tt_connection.user_accounts_cache: # Checked by middleware, but defensive
            logger.warning("USER_ACCOUNTS_CACHE is empty or tt_connection not available for LINK_NEW.")
            await query.answer(_("TeamTalk server accounts cache is not populated or connection error. Please try again later."), show_alert=True)
            return

        server_accounts: list[pytalk.UserAccount] = list(tt_connection.user_accounts_cache.values())
        if not server_accounts:
            await query.answer(_("No TeamTalk server accounts found on {server_host} or unable to fetch.").format(server_host=tt_connection.server_info.host), show_alert=True)
            return

        link_keyboard = create_linkable_tt_account_list_keyboard(
            _, page_items=server_accounts, current_page_idx=0, total_pages=1, # Assuming single page for now
            target_telegram_id=target_telegram_id, subscriber_list_page=return_page
        )
        await query.message.edit_text(
            _("Select a TeamTalk account from {server_host} to link to subscriber {telegram_id}:").format(server_host=tt_connection.server_info.host, telegram_id=target_telegram_id),
            reply_markup=link_keyboard
        )
        await query.answer()
        return

    else:
        await query.answer(_("Unknown manage account action."), show_alert=True)
        logger.warning(f"Unknown manage TT account action: {action}")


# Removed F.from_user.id.in_(ADMIN_IDS_CACHE)
@subscriber_actions_router.callback_query(LinkTTAccountChosenCallback.filter())
async def handle_link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    session: AsyncSession,
    _: callable,
    app: "Application" # Inject app
):
    if query.from_user.id not in app.admin_ids_cache:
        await query.answer(_("You are not authorized for this action."), show_alert=True)
        return

    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page

    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        await query.answer(
            _("This TeamTalk username ({tt_username}) is banned and cannot be linked.").format(tt_username=tt_username_to_link),
            show_alert=True
        )
        user_s = await session.get(UserSettings, target_telegram_id)
        current_tt_username = user_s.teamtalk_username if user_s else None
        kb = create_manage_tt_account_keyboard(_, target_telegram_id, current_tt_username, return_page)
        await query.message.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=kb
        )
        return

    user_settings = await session.get(UserSettings, target_telegram_id)
    if not user_settings:
        await query.answer(_("User settings not found for this subscriber."), show_alert=True)
        return

    old_tt_username = user_settings.teamtalk_username
    user_settings.teamtalk_username = tt_username_to_link
    user_settings.not_on_online_confirmed = False
    await session.commit()
    await session.refresh(user_settings)
    # Update global USER_SETTINGS_CACHE. If app-managed, use app.user_settings_cache
    app.user_settings_cache[user_settings.telegram_id] = user_settings


    alert_text = _("TeamTalk account {new_tt_username} linked successfully.").format(new_tt_username=tt_username_to_link)
    if old_tt_username and old_tt_username != tt_username_to_link:
        alert_text += " " + _("(Replaced {old_tt_username})").format(old_tt_username=old_tt_username)
    await query.answer(alert_text, show_alert=True)

    keyboard = create_manage_tt_account_keyboard(_, target_telegram_id=target_telegram_id, current_tt_username=tt_username_to_link, page=return_page)
    await query.message.edit_text(
         _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
        reply_markup=keyboard
    )
