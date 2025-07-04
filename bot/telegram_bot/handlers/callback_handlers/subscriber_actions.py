import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramAPIError # Added import
from sqlalchemy.ext.asyncio import AsyncSession
from pytalk.instance import TeamTalkInstance # For TeamTalk actions like ban/kick if needed directly

from bot.telegram_bot.callback_data import (
    ViewSubscriberCallback,
    SubscriberActionCallback,
    ManageTTAccountCallback,
    LinkTTAccountChosenCallback,
    SubscriberListCallback # For "Back" button to subscriber list
)
from bot.telegram_bot.keyboards import (
    create_subscriber_action_menu_keyboard,
    create_manage_tt_account_keyboard,
    create_linkable_tt_account_list_keyboard,
    create_subscriber_list_keyboard # Added direct import
    # We might need create_account_list_keyboard if we adapt it, or a new one
)
from bot.models import UserSettings, BanList # For fetching UserSettings, interacting with BanList
from bot.database import crud # For BanList and UserSettings CRUD
from bot.services import user_service # For deleting user
from bot.state import ADMIN_IDS_CACHE, USER_ACCOUNTS_CACHE
from bot.core.enums import SubscriberListAction, SubscriberAction, ManageTTAccountAction
from bot.telegram_bot.middlewares import TeamTalkConnectionMiddleware
import pytalk # To get UserAccount type for list[pytalk.UserAccount]
from .list_utils import _get_paginated_subscribers_info # Import from list_utils
from bot.telegram_bot.utils import format_telegram_user_display_name

logger = logging.getLogger(__name__)
subscriber_actions_router = Router(name="subscriber_actions_router")
# Apply to all callback query handlers in this router
subscriber_actions_router.callback_query.middleware(TeamTalkConnectionMiddleware())

# This router will need to be included in the main dispatcher.

async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    return_page: int,
    _: callable
):
    """Refreshes and displays the subscriber list in the query's message."""
    if not query.message: # Should ideally be checked by caller too
        logger.warning("_refresh_and_display_subscriber_list called with no message context.")
        await query.answer(_("Error: Message context lost."), show_alert=True) # Attempt to notify user
        return

    page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
        session, bot, return_page
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
    # query.answer() is not called here, assuming prior action (delete/ban) did it. Or it's handled by send_or_edit_paginated_list if that was used.
    # For this refactor, the original calls to query.answer() for delete/ban success/failure remain in the main handler.

@subscriber_actions_router.callback_query(ViewSubscriberCallback.filter(), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def handle_view_subscriber(
    query: CallbackQuery,
    callback_data: ViewSubscriberCallback,
    session: AsyncSession, # For potential DB operations if needed directly
    _: callable # Translator
):
    """Displays the action menu for a specific subscriber."""
    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    keyboard = create_subscriber_action_menu_keyboard(
        _,
        target_telegram_id=callback_data.telegram_id,
        page=callback_data.page
    )

    # You might want to display some info about the user here too.
    # For now, just showing the action menu.
    # Fetching user details to display:
    user_to_view = await session.get(UserSettings, callback_data.telegram_id)
    display_name = str(callback_data.telegram_id) # Default display name
    chat_info = None
    if user_to_view and user_to_view.telegram_id: # Check if user_to_view is not None
        try:
            chat_info = await query.bot.get_chat(user_to_view.telegram_id)
            # Use the new helper function if chat_info was successfully fetched
            display_name = format_telegram_user_display_name(chat_info)
        except TelegramAPIError as e_tg:
            logger.error(f"Could not fetch chat info for {user_to_view.telegram_id} via Telegram API: {e_tg}", exc_info=True)
            # display_name remains callback_data.telegram_id (as set above)
        except Exception as e: # Fallback for truly unexpected errors
            logger.error(f"Unexpected error fetching chat info for {user_to_view.telegram_id}: {e}", exc_info=True)
            # If chat_info fetch fails, display_name remains callback_data.telegram_id (as set above)
            # or potentially format_telegram_user_display_name(None) if we want consistent handling
            # but the original code kept it as the ID.
            # For safety, if chat_info is None, format_telegram_user_display_name might return "Unknown User"
            # or str(chat.id) if it received a None chat object that somehow had an id.
            # Sticking to original fallback:
            # display_name = str(callback_data.telegram_id) # already set

    text = _("Actions for subscriber: {display_name}").format(display_name=display_name)
    if user_to_view and user_to_view.teamtalk_username:
        text += _("\nLinked TeamTalk account: {tt_username}").format(tt_username=user_to_view.teamtalk_username)

    await query.message.edit_text(
        text,
        reply_markup=keyboard
    )
    await query.answer()


@subscriber_actions_router.callback_query(SubscriberActionCallback.filter(), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def handle_subscriber_action(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    bot: Bot, # For bot.get_chat if needed
    tt_instance: TeamTalkInstance, # Middleware ensures this is valid for actions needing it
    _: callable # Translator
):
    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    if action == SubscriberAction.DELETE:
        success = await user_service.delete_full_user_profile(session, target_telegram_id)
        if success:
            await query.answer(_("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id), show_alert=True)
            await _refresh_and_display_subscriber_list(query, session, bot, return_page, _)
        else:
            await query.answer(_("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id), show_alert=True)
        return # Explicit return after handling delete

    elif action == SubscriberAction.BAN:
        user_settings = await session.get(UserSettings, target_telegram_id)
        tt_username_to_ban = user_settings.teamtalk_username if user_settings else None

        banned_tg = await crud.add_to_ban_list(session, telegram_id=target_telegram_id, reason="Banned by admin via subscriber menu")
        banned_tt = False
        if tt_username_to_ban:
            banned_tt = await crud.add_to_ban_list(session, teamtalk_username=tt_username_to_ban, reason=f"Banned by admin (linked to TG ID: {target_telegram_id})")
            # Optional: Actual TeamTalk server ban via tt_instance if user is online
            # tt_instance here is from handle_subscriber_action's parameters.
            # If tt_instance is None (because middleware didn't run for this specific path or it's optional), this check is fine.
            # However, subscriber_actions_router now has the middleware, so tt_instance should be valid.
            # Let's change its type hint to non-optional for this handler.
            if tt_instance: # tt_instance should be valid due to router middleware
                try:
                    # Find user by username and ban. This requires pytalk SDK for ban by username/IP.
                    # For now, we assume ban is DB-side for future /sub checks.
                    logger.info(f"Conceptual TeamTalk server ban for {tt_username_to_ban} (not implemented in this step, tt_instance available)")
                except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError) as e_tt: # For future pytalk calls
                    logger.error(f"Error during conceptual TeamTalk ban for {tt_username_to_ban}: {e_tt}", exc_info=True)
                except Exception as e: # Fallback for truly unexpected errors if the future code does something else
                    logger.error(f"Unexpected error during conceptual TeamTalk ban for {tt_username_to_ban}: {e}", exc_info=True)
            else:
                # This case should ideally not be reached if middleware is correctly applied and tt_instance is made non-optional
                logger.warning(f"Skipping conceptual TeamTalk ban for {tt_username_to_ban} as tt_instance is None/invalid.")


        # After banning, also delete their subscription and settings data
        await user_service.delete_full_user_profile(session, target_telegram_id)

        # Consolidate messages
        ban_messages = []
        if banned_tg:
            ban_messages.append(_("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id))
        if tt_username_to_ban and banned_tt:
            ban_messages.append(_("TeamTalk username {tt_username} banned.").format(tt_username=tt_username_to_ban))

        if not ban_messages:
            alert_message = _("User already banned or error occurred.")
        else:
            alert_message = " ".join(ban_messages)
            alert_message += " " + _("Subscriber data also deleted.")

        await query.answer(alert_message, show_alert=True)
        await _refresh_and_display_subscriber_list(query, session, bot, return_page, _)
        return # Explicit return

    elif action == SubscriberAction.MANAGE_TT_ACCOUNT:
        user_settings = await session.get(UserSettings, target_telegram_id)
        current_tt_username = user_settings.teamtalk_username if user_settings else None

        keyboard = create_manage_tt_account_keyboard(
            _,
            target_telegram_id=target_telegram_id,
            current_tt_username=current_tt_username,
            page=return_page
        )
        await query.message.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=keyboard
        )
        await query.answer()
        return # Explicit return

    else:
        await query.answer(_("Unknown action."), show_alert=True)
        logger.warning(f"Unknown subscriber action: {action}")


@subscriber_actions_router.callback_query(ManageTTAccountCallback.filter(), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def handle_manage_tt_account(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    session: AsyncSession,
    tt_instance: TeamTalkInstance, # Middleware ensures this is valid and connected for LINK_NEW
    _: callable
):
    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page # Page of the main subscriber list

    user_settings = await session.get(UserSettings, target_telegram_id)
    if not user_settings:
        await query.answer(_("User settings not found for this subscriber."), show_alert=True)
        # Potentially send back to subscriber list or main menu
        return

    if action == ManageTTAccountAction.UNLINK:
        if user_settings.teamtalk_username:
            unlinked_tt_username = user_settings.teamtalk_username
            user_settings.teamtalk_username = None
            user_settings.not_on_online_confirmed = False # Reset NOON confirmation
            await session.commit()
            await session.refresh(user_settings)
            await query.answer(_("TeamTalk account {tt_username} unlinked.").format(tt_username=unlinked_tt_username), show_alert=True)
        else:
            await query.answer(_("No TeamTalk account was linked."), show_alert=True)

        # Refresh the manage_tt menu
        keyboard = create_manage_tt_account_keyboard(
            _, target_telegram_id=target_telegram_id, current_tt_username=None, page=return_page
        )
        await query.message.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=keyboard
        )
        return # Explicit return

    elif action == ManageTTAccountAction.LINK_NEW:
        # tt_instance is guaranteed by middleware.
        # We still need to check USER_ACCOUNTS_CACHE as it's populated separately.
        if not USER_ACCOUNTS_CACHE:
            logger.warning("USER_ACCOUNTS_CACHE is empty while trying to link TT account.")
            await query.answer(_("TeamTalk server accounts cache is not populated. Please try again later."), show_alert=True)
            return

        server_accounts: list[pytalk.UserAccount] = list(USER_ACCOUNTS_CACHE.values())

        if not server_accounts: # Should be redundant if USER_ACCOUNTS_CACHE check above is robust
            await query.answer(_("No TeamTalk server accounts found or unable to fetch."), show_alert=True)
            return

        # For simplicity, assuming server_accounts is not paginated here.
        # If it needs pagination, that's a further enhancement to create_linkable_tt_account_list_keyboard
        # and LinkTTAccountChosenCallback might need a page index for the account list.
        link_keyboard = create_linkable_tt_account_list_keyboard(
            _,
            page_items=server_accounts,
            current_page_idx=0, # Assuming single page for now
            total_pages=1,      # Assuming single page for now
            target_telegram_id=target_telegram_id,
            subscriber_list_page=return_page
        )
        await query.message.edit_text(
            _("Select a TeamTalk account to link to subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=link_keyboard
        )
        await query.answer()
        return # Explicit return

    else:
        await query.answer(_("Unknown manage account action."), show_alert=True)
        logger.warning(f"Unknown manage TT account action: {action}")


@subscriber_actions_router.callback_query(LinkTTAccountChosenCallback.filter(), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def handle_link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    session: AsyncSession,
    _: callable
):
    if not query.message:
        await query.answer(_("Error: Message context lost."), show_alert=True)
        return

    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page # Page of the main subscriber list

    # Check if the chosen TeamTalk username is banned
    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        await query.answer(
            _("This TeamTalk username ({tt_username}) is banned and cannot be linked.").format(tt_username=tt_username_to_link),
            show_alert=True
        )
        # Optionally, redisplay the "Manage TT Account" menu or the TT account list
        # For now, just show alert. To be more user-friendly, one might re-render the previous menu.
        # Re-rendering the "Manage TT Account" menu:
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
        # This case should ideally be handled before even showing the link list.
        return

    old_tt_username = user_settings.teamtalk_username
    user_settings.teamtalk_username = tt_username_to_link
    user_settings.not_on_online_confirmed = False # Reset NOON confirmation if account changes
    await session.commit()
    await session.refresh(user_settings)

    alert_text = _("TeamTalk account {new_tt_username} linked successfully.").format(new_tt_username=tt_username_to_link)
    if old_tt_username and old_tt_username != tt_username_to_link:
        alert_text += " " + _("(Replaced {old_tt_username})").format(old_tt_username=old_tt_username)

    await query.answer(alert_text, show_alert=True)

    # Refresh the "Manage TT Account" menu to show the new state
    keyboard = create_manage_tt_account_keyboard(
        _,
        target_telegram_id=target_telegram_id,
        current_tt_username=tt_username_to_link, # Newly linked username
        page=return_page
    )
    await query.message.edit_text(
         _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
        reply_markup=keyboard
    )
