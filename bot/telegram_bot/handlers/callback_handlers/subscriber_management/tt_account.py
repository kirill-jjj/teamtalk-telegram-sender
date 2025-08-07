"""Callback query handlers for subscriber's TeamTalk account management."""

from gettext import NullTranslations
import logging
from typing import cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka
import pytalk

from bot.core.enums import ManageTTAccountAction, SubscriberCommand
from bot.database.repositories.user_repository import UserRepository
from bot.models import OperationResult
from bot.services.subscription_service import SubscriptionService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    PaginateLinkableAccountsCallback,
    SubscriberCallback,
)
from bot.telegram_bot.handlers.callback_handlers._helpers import ensure_message_context
from bot.telegram_bot.handlers.callback_handlers.list_utils import SUBSCRIBERS_PER_PAGE
from bot.telegram_bot.keyboards import (
    create_linkable_tt_account_list_keyboard,
    create_manage_tt_account_keyboard,
)
from bot.telegram_bot.ui_utils import display_paginated_list, safe_edit_text

logger = logging.getLogger(__name__)
tt_account_router = Router(name="subscriber_management.tt_account_router")


@tt_account_router.callback_query(
    SubscriberCallback.filter(F.action == SubscriberCommand.MANAGE_TT_ACCOUNT)
)
@ensure_message_context
async def manage_tt_account(
    query: CallbackQuery,
    callback_data: SubscriberCallback,
    translator: FromDishka[NullTranslations],
    user_repo: FromDishka[UserRepository],
) -> None:
    """Shows the menu to manage a subscriber's linked TeamTalk account."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    user_settings = await user_repo.get_by_id(target_telegram_id)
    current_tt_username = user_settings.teamtalk_username if user_settings else None

    keyboard = await create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=current_tt_username,
        page=return_page,
    )
    message_text = _(
        "Manage TeamTalk account link for subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)

    await safe_edit_text(
        message_to_edit=cast(Message, query.message),
        text=message_text,
        reply_markup=keyboard,
    )
    await query.answer()


@tt_account_router.callback_query(
    ManageTTAccountCallback.filter(F.action == ManageTTAccountAction.LINK_NEW)
)
@ensure_message_context
async def link_new_tt_account_choice(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    translator: FromDishka[NullTranslations],
    tt_connection: TeamTalkConnection,
) -> None:
    """Handle 'Link/Change TeamTalk Account' action by showing linkable accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.page,
        linkable_accounts_page_to_show=0,
        tt_connection=tt_connection,
        translator=translator,
    )


async def _display_linkable_tt_accounts_page(
    query: CallbackQuery,
    target_telegram_id: int,
    subscriber_context_page: int,
    linkable_accounts_page_to_show: int,
    tt_connection: TeamTalkConnection,
    translator: NullTranslations,
) -> None:
    """Helper to display a paginated list of linkable TeamTalk accounts."""
    _ = translator.gettext

    if not tt_connection.is_ready or not tt_connection.user_accounts_cache:
        logger.warning(
            "TeamTalk connection not ready or USER_ACCOUNTS_CACHE is empty for "
            "displaying linkable accounts. User %s.",
            query.from_user.id,
        )
        await query.answer(
            _(
                "TeamTalk server accounts are currently unavailable. "
                "Please try again later."
            ),
            show_alert=True,
        )
        return

    all_server_accounts: list[pytalk.UserAccount] = list(
        tt_connection.user_accounts_cache.values()
    )

    try:
        sdk_ttstr = pytalk.instance.sdk.ttstr
        all_server_accounts.sort(
            key=lambda acc: (
                sdk_ttstr(acc.username).lower()
                if isinstance(acc.username, str | bytes)
                else str(acc.username).lower()
            )
        )
    except Exception:
        logger.exception(
            "Error sorting server accounts for user %s. Proceeding with unsorted list.",
            query.from_user.id,
        )

    title_text = _(
        "Select a TeamTalk account from {server_host} to link to subscriber "
        "{telegram_id}:"
    ).format(server_host=tt_connection.server_info.host, telegram_id=target_telegram_id)
    empty_list_text = _("No TeamTalk server accounts found on {server_host}.").format(
        server_host=tt_connection.server_info.host
    )
    if not all_server_accounts:
        empty_list_text = _(
            "No TeamTalk server accounts found on {server_host} or unable to fetch."
        ).format(server_host=tt_connection.server_info.host)
    if query.bot is None:
        logger.error(
            "_display_linkable_tt_accounts_page: query.bot is None. "
            "Cannot display list."
        )
        await query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    await display_paginated_list(
        target=query,
        bot=query.bot,
        translator=translator,
        items=all_server_accounts,
        page=linkable_accounts_page_to_show,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_linkable_tt_account_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_list_page": subscriber_context_page,
        },
        page_size=SUBSCRIBERS_PER_PAGE,
        server_host_for_display=None,
    )


@tt_account_router.callback_query(PaginateLinkableAccountsCallback.filter())
@ensure_message_context
async def paginate_linkable_accounts(
    query: CallbackQuery,
    callback_data: PaginateLinkableAccountsCallback,
    tt_connection: TeamTalkConnection,
    translator: FromDishka[NullTranslations],
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


@tt_account_router.callback_query(LinkTTAccountChosenCallback.filter())
@ensure_message_context
async def link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    translator: FromDishka[NullTranslations],
    user_repo: FromDishka[UserRepository],
    subscription_service: FromDishka[SubscriptionService],
) -> None:
    """Handles linking a chosen TeamTalk account to a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    tt_username_to_link = callback_data.tt_username
    return_page = callback_data.page

    user_settings = await user_repo.get_by_id(target_telegram_id)
    if not user_settings:
        await query.answer(_("Subscriber not found."), show_alert=True)
        return

    operation_result: OperationResult = await subscription_service.link_tt_account(
        user_settings, tt_username_to_link
    )

    alert_message_args = operation_result.message_args or {}
    if "tt_username" not in alert_message_args:
        alert_message_args["tt_username"] = tt_username_to_link
    if "new_tt_username" not in alert_message_args:
        alert_message_args["new_tt_username"] = tt_username_to_link

    alert_message = _(operation_result.message_key).format(**alert_message_args)
    await query.answer(alert_message, show_alert=True)

    final_tt_username_for_keyboard: str | None
    if operation_result.success and operation_result.user_settings:
        final_tt_username_for_keyboard = (
            operation_result.user_settings.teamtalk_username
        )
    else:
        user_s_for_kb = await user_repo.get_by_id(target_telegram_id)
        final_tt_username_for_keyboard = (
            user_s_for_kb.teamtalk_username if user_s_for_kb else None
        )

    updated_keyboard = await create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=final_tt_username_for_keyboard,
        page=return_page,
    )
    await cast(Message, query.message).edit_text(
        _("Manage TeamTalk account link for subscriber {telegram_id}:").format(
            telegram_id=target_telegram_id
        ),
        reply_markup=updated_keyboard,
    )
