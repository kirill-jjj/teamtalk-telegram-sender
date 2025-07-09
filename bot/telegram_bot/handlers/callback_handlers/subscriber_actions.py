"""Callback query handlers for actions related to specific subscribers."""

import gettext  # Added gettext
import logging

# For type hinting app instance
from typing import TYPE_CHECKING

from aiogram import Router  # Bot can be imported from here if needed by other parts, or directly
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message  # Added Message

# If Bot is needed for type hinting services.bot_event explicitly, import it as `from aiogram import Bot`
import pytalk
from sqlmodel.ext.asyncio.session import AsyncSession  # Changed to SQLModel's AsyncSession

from bot.core.enums import ManageTTAccountAction, SubscriberAction
from bot.database import crud
from bot.models import UserSettings
from bot.services import user_service
from bot.teamtalk_bot.connection import TeamTalkConnection  # For type hinting
from bot.telegram_bot.callback_data import (
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    SubscriberActionCallback,
    ViewSubscriberCallback,
)
from bot.telegram_bot.keyboards import (
    create_linkable_tt_account_list_keyboard,
    create_manage_tt_account_keyboard,
    create_subscriber_action_menu_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware
from bot.telegram_bot.utils import format_telegram_user_display_name

from .list_utils import _get_paginated_subscribers_info

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
subscriber_actions_router = Router(name="subscriber_actions_router")
subscriber_actions_router.callback_query.middleware(
    ActiveTeamTalkConnectionMiddleware(default_server_key=None)
)  # Added
subscriber_actions_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())  # Existing


async def _refresh_and_display_subscriber_list(
    query: CallbackQuery,
    session: AsyncSession,
    services: "Services",
    return_page: int,
    translator: gettext.GNUTranslations,
) -> None:
    _ = translator.gettext
    active_bot = services.bot_event  # Get bot from services
    if not query.message:
        logger.warning("_refresh_and_display_subscriber_list called with no message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    message_obj = query.message # Assign before use
    if not isinstance(message_obj, Message):
        logger.warning("_refresh_and_display_subscriber_list: Message is None or inaccessible.")
        # Already answered callback if message was None initially.
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
        await message_obj.edit_text(
            _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
                current_page_display=current_page + 1, total_pages=total_pages
            ),
            reply_markup=new_keyboard,
        )


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
    if not query.message:  # Should be caught by @ensure_message_context if applied, but good practice.
        logger.warning("handle_view_subscriber called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    keyboard = await create_subscriber_action_menu_keyboard(
        translator, target_telegram_id=callback_data.telegram_id, page=callback_data.page
    )
    user_to_view = await session.get(UserSettings, callback_data.telegram_id)
    display_name = str(callback_data.telegram_id)

    # Use services.bot_event for get_chat
    active_bot = services.bot_event
    if user_to_view and user_to_view.telegram_id:
        try:
            chat_info = await active_bot.get_chat(user_to_view.telegram_id)
            display_name = format_telegram_user_display_name(chat_info)
        except TelegramAPIError:  # Removed 'as e_tg'
            logger.exception(
                "Could not fetch chat info for %s via Telegram API.",
                user_to_view.telegram_id,
            )
        except Exception:
            logger.exception("Unexpected error fetching chat info for %s.", user_to_view.telegram_id)

    if user_to_view and user_to_view.teamtalk_username:
        text = _("Actions for subscriber: {display_name}\nLinked TeamTalk account: {tt_username}").format(
            display_name=display_name, tt_username=user_to_view.teamtalk_username
        )
    else:
        text = _("Actions for subscriber: {display_name}").format(display_name=display_name)

    message_obj = query.message
    if isinstance(message_obj, Message):
        await message_obj.edit_text(text, reply_markup=keyboard)
    else:
        logger.warning("handle_view_subscriber: Message is None or inaccessible.")
        # Cannot edit, but still answer the query if not already done.
        # Query answer might have happened earlier if message was None initially.
    await query.answer()


async def _handle_delete_subscriber_action(
    query: CallbackQuery,
    session: AsyncSession,
    # active_bot: AiogramBot, # Removed
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles the deletion of a subscriber."""
    _ = translator.gettext
    if not query.message:  # Should be caught by @ensure_message_context if applied
        logger.warning("_handle_delete_subscriber_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    success = await user_service.delete_full_user_profile(session, target_telegram_id, services=services)
    if success:
        await query.answer(
            _("Subscriber {telegram_id} deleted successfully.").format(telegram_id=target_telegram_id),
            show_alert=True,
        )
        await _refresh_and_display_subscriber_list(query, session, services, return_page, translator)  # Pass services
    else:
        await query.answer(
            _("Error deleting subscriber {telegram_id}.").format(telegram_id=target_telegram_id), show_alert=True
        )


# The main dispatcher function will call these helpers.
@subscriber_actions_router.callback_query(SubscriberActionCallback.filter())
async def handle_subscriber_action(
    query: CallbackQuery,
    callback_data: SubscriberActionCallback,
    session: AsyncSession,
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles actions performed on a subscriber (delete, ban, manage TT account)."""
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    action = callback_data.action
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    if action == SubscriberAction.DELETE:
        await _handle_delete_subscriber_action(
            query,
            session,
            target_telegram_id,
            return_page,
            translator,
            services,  # Pass services directly
        )
    elif action == SubscriberAction.BAN:
        await _handle_ban_subscriber_action(
            query,
            session,
            services,  # Pass services directly
            tt_connection,
            target_telegram_id,
            return_page,
            translator,
        )
    elif action == SubscriberAction.MANAGE_TT_ACCOUNT:
        await _handle_manage_tt_account_action(query, session, target_telegram_id, return_page, translator)
    else:
        await query.answer(_("Unknown action."), show_alert=True)
        logger.warning("Unknown subscriber action: %s", action)


async def _handle_ban_subscriber_action(
    query: CallbackQuery,
    session: AsyncSession,
    # active_bot: AiogramBot, # Removed
    services: "Services",  # Added services directly
    tt_connection: TeamTalkConnection | None,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
    # services: "Services", # Already present, ensure it's used correctly
) -> None:
    """Handles banning a subscriber (TG and linked TT account)."""
    _ = translator.gettext
    if not query.message:  # Should be caught by @ensure_message_context if applied
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
            session,
            teamtalk_username=tt_username_to_ban,
            reason=f"Banned by admin (linked to TG ID: {target_telegram_id})",
        )
        if tt_connection and tt_connection.instance:
            try:
                # Conceptual: Actual TT server ban would happen here.
                logger.info(
                    "Conceptual TeamTalk server ban for %s on %s (not implemented in this step)",
                    tt_username_to_ban,
                    tt_connection.server_info.host,
                )
            except (pytalk.exceptions.TeamTalkException, TimeoutError, OSError):  # Removed 'as e_tt'
                logger.exception(
                    "Error during conceptual TeamTalk ban for %s on %s.",  # Removed trailing : %s
                    tt_username_to_ban,
                    tt_connection.server_info.host,
                )
            except Exception:
                logger.exception(
                    "Unexpected error during conceptual TeamTalk ban for %s on %s.",
                    tt_username_to_ban,
                    tt_connection.server_info.host,
                )
        else:
            logger.warning(
                "Skipping conceptual TeamTalk ban for %s as tt_connection or its instance is None/invalid.",
                tt_username_to_ban,
            )

    await user_service.delete_full_user_profile(session, target_telegram_id, services=services)

    ban_messages = []
    if banned_tg:
        ban_messages.append(_("Telegram ID {telegram_id} banned.").format(telegram_id=target_telegram_id))
    if tt_username_to_ban and banned_tt:
        ban_messages.append(_("TeamTalk username {tt_username} banned.").format(tt_username=tt_username_to_ban))

    alert_message = " ".join(ban_messages)
    if alert_message:
        alert_message = _("{ban_report} Subscriber data also deleted.").format(ban_report=alert_message)
    else:
        alert_message = _("User already banned or error occurred.")

    await query.answer(alert_message, show_alert=True)
    await _refresh_and_display_subscriber_list(query, session, services, return_page, translator)  # Pass services


async def _handle_manage_tt_account_action(
    query: CallbackQuery,
    session: AsyncSession,
    target_telegram_id: int,
    return_page: int,
    translator: gettext.GNUTranslations,
) -> None:
    """Handles showing the menu to manage a subscriber's linked TT account."""
    _ = translator.gettext
    if not query.message:  # Should be caught by @ensure_message_context if applied
        logger.warning("_handle_manage_tt_account_action called without message context.")
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    user_settings = await session.get(UserSettings, target_telegram_id)
    current_tt_username = user_settings.teamtalk_username if user_settings else None
    keyboard = await create_manage_tt_account_keyboard(
        translator, target_telegram_id=target_telegram_id, current_tt_username=current_tt_username, page=return_page
    )
    message_obj = query.message
    if isinstance(message_obj, Message):
        await message_obj.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=keyboard,
        )
    else:
        logger.warning("_handle_manage_tt_account_action: Message is None or inaccessible.")
    await query.answer()


@subscriber_actions_router.callback_query(ManageTTAccountCallback.filter())
async def handle_manage_tt_account(  # This function itself might become a dispatcher for sub-actions
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    session: AsyncSession,
    tt_connection: TeamTalkConnection | None,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> None:
    """Handles managing a subscriber's linked TeamTalk account (unlink, link new)."""
    _ = translator.gettext
    if not query.message:
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
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
            services.cache.update_user_settings(user_settings)  # Use CacheService
            await query.answer(
                _("TeamTalk account {tt_username} unlinked.").format(tt_username=unlinked_tt_username), show_alert=True
            )
        else:
            await query.answer(_("No TeamTalk account was linked."), show_alert=True)

        keyboard = await create_manage_tt_account_keyboard(
            translator, target_telegram_id=target_telegram_id, current_tt_username=None, page=return_page
        )
        message_obj = query.message
        if isinstance(message_obj, Message):
            await message_obj.edit_text(
                _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
                reply_markup=keyboard,
            )
        else:
            logger.warning("handle_manage_tt_account (unlink): Message is None or inaccessible.")
        return

    if action == ManageTTAccountAction.LINK_NEW:
        if not tt_connection or not tt_connection.user_accounts_cache:
            logger.warning("USER_ACCOUNTS_CACHE is empty or tt_connection not available for LINK_NEW.")
            await query.answer(
                _("TeamTalk server accounts cache is not populated or connection error. Please try again later."),
                show_alert=True,
            )
            return

        server_accounts: list[pytalk.UserAccount] = list(tt_connection.user_accounts_cache.values())
        if not server_accounts:
            await query.answer(
                _("No TeamTalk server accounts found on {server_host} or unable to fetch.").format(
                    server_host=tt_connection.server_info.host
                ),
                show_alert=True,
            )
            return

        link_keyboard = await create_linkable_tt_account_list_keyboard(
            translator,
            page_items=server_accounts,
            current_page_idx=0,
            total_pages=1,
            target_telegram_id=target_telegram_id,
            subscriber_list_page=return_page,
        )
        message_obj = query.message
        if isinstance(message_obj, Message):
            await message_obj.edit_text(
                _("Select a TeamTalk account from {server_host} to link to subscriber {telegram_id}:").format(
                    server_host=tt_connection.server_info.host, telegram_id=target_telegram_id
                ),
                reply_markup=link_keyboard,
            )
        else:
            logger.warning("handle_manage_tt_account (link_new): Message is None or inaccessible.")
        await query.answer()
        return

    await query.answer(_("Unknown action."), show_alert=True)
    logger.warning("Unknown subscriber action: %s", action)


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
    if not query.message:
        await query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page

    if await crud.is_teamtalk_username_banned(session, tt_username_to_link):
        await query.answer(
            _("This TeamTalk username ({tt_username}) is banned and cannot be linked.").format(
                tt_username=tt_username_to_link
            ),
            show_alert=True,
        )
        user_s = await session.get(UserSettings, target_telegram_id)
        current_tt_username = user_s.teamtalk_username if user_s else None
        kb = await create_manage_tt_account_keyboard(translator, target_telegram_id, current_tt_username, return_page)
        message_obj = query.message
        if isinstance(message_obj, Message):
            await message_obj.edit_text(
                _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
                reply_markup=kb,
            )
        else:
            logger.warning("handle_link_tt_account_chosen (banned): Message is None or inaccessible.")
        return

    user_settings = await session.get(UserSettings, target_telegram_id)
    if not user_settings:
        await query.answer(_("User settings not found for this subscriber."), show_alert=True)
        return

    old_tt_username = user_settings.teamtalk_username
    user_settings.teamtalk_username = tt_username_to_link
    user_settings.not_on_online_confirmed = True  # Linking by admin implies confirmation for NOON
    await session.commit()
    await session.refresh(user_settings)
    services.cache.update_user_settings(user_settings)  # Use CacheService

    alert_text = _("TeamTalk account {new_tt_username} linked successfully.").format(
        new_tt_username=tt_username_to_link
    )
    if old_tt_username and old_tt_username != tt_username_to_link:
        alert_text += " " + _("(Replaced {old_tt_username})").format(old_tt_username=old_tt_username)
    await query.answer(alert_text, show_alert=True)

    keyboard = await create_manage_tt_account_keyboard(
        translator, target_telegram_id=target_telegram_id, current_tt_username=tt_username_to_link, page=return_page
    )
    message_obj = query.message
    if isinstance(message_obj, Message):
        await message_obj.edit_text(
            _("Manage TeamTalk account link for subscriber {telegram_id}:").format(telegram_id=target_telegram_id),
            reply_markup=keyboard,
        )
    else:
        logger.warning("handle_link_tt_account_chosen (success): Message is None or inaccessible.")
