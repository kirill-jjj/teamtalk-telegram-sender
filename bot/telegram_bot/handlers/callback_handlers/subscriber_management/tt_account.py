"""Callback query handlers for subscriber's TeamTalk account management."""

from gettext import NullTranslations
import logging
from typing import Annotated, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.commands import GetAllTeamTalkAccountsCommand, GetAllTeamTalkAccountsResult
from bot.constants import MSG_GENERAL_ERROR, USERS_PER_PAGE
from bot.core.enums import Actor, ManageTTAccountAction, SubscriberCommand
from bot.database.uow import IUnitOfWork
from bot.services.schemas import UserAccountInfo
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import (
    LinkTTAccountChosenCallback,
    ManageTTAccountCallback,
    PaginateLinkableAccountsCallback,
    SubscriberCallback,
)
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import (
    create_linkable_tt_account_list_keyboard,
    create_manage_tt_account_keyboard,
)
from bot.telegram_bot.ui_utils import (
    display_paginated_list,
    edit_message_text,
)
from bot.utils.pagination import paginate_list

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
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Shows the menu to manage a subscriber's linked TeamTalk account."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    async with uow:
        data = await user_settings_service.get_account_management_data(
            uow, target_telegram_id
        )

    keyboard = create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=data.current_tt_username,
        page=return_page,
    )
    message_text = _(
        "Manage TeamTalk account link for subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)

    await edit_message_text(
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
    command_bus: Annotated[CommandBus, FromDishka()],
) -> None:
    """Handle 'Link/Change TeamTalk Account' action by showing linkable accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.page,
        linkable_accounts_page_to_show=0,
        command_bus=command_bus,
        translator=translator,
    )
    await query.answer()


async def _display_linkable_tt_accounts_page(
    query: CallbackQuery,
    target_telegram_id: int,
    subscriber_context_page: int,
    linkable_accounts_page_to_show: int,
    command_bus: CommandBus,
    translator: NullTranslations,
) -> None:
    """Helper to display a paginated list of linkable TeamTalk accounts."""
    _ = translator.gettext

    result: GetAllTeamTalkAccountsResult = await command_bus.execute(
        GetAllTeamTalkAccountsCommand(lang_code=translator.info().get("language", "en"))
    )

    if not result.success:
        logger.warning(
            "Failed to get TeamTalk accounts for linking. User %s. Error: %s",
            query.from_user.id,
            result.error_message,
        )
        await query.answer(result.error_message, show_alert=True)
        return

    all_server_accounts: list[UserAccountInfo] = result.accounts

    try:
        all_server_accounts.sort(key=lambda acc: acc.username.lower())
    except TypeError:
        logger.exception(
            "Error sorting server accounts for user %s. Proceeding with unsorted list.",
            query.from_user.id,
        )

    title_text = _(
        "Select a TeamTalk account to link to subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)
    empty_list_text = _("No TeamTalk server accounts found.")

    if not all_server_accounts:
        empty_list_text = _("No TeamTalk server accounts found or unable to fetch.")

    if query.bot is None:
        logger.error(
            "_display_linkable_tt_accounts_page: query.bot is None. "
            "Cannot display list."
        )
        await query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
        return

    page_slice, _, current_page_idx = paginate_list(
        all_server_accounts, linkable_accounts_page_to_show, USERS_PER_PAGE
    )

    await display_paginated_list(
        target=query,
        bot=query.bot,
        translator=translator,
        items_on_page=page_slice,
        total_items=len(all_server_accounts),
        page=current_page_idx,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_linkable_tt_account_list_keyboard,
        keyboard_factory_kwargs={
            "target_telegram_id": target_telegram_id,
            "subscriber_list_page": subscriber_context_page,
        },
        page_size=USERS_PER_PAGE,
        server_host_for_display=None,
    )


@tt_account_router.callback_query(PaginateLinkableAccountsCallback.filter())
@ensure_message_context
async def paginate_linkable_accounts(
    query: CallbackQuery,
    callback_data: PaginateLinkableAccountsCallback,
    command_bus: Annotated[CommandBus, FromDishka()],
    translator: FromDishka[NullTranslations],
) -> None:
    """Handles pagination for the list of linkable TeamTalk accounts."""
    await _display_linkable_tt_accounts_page(
        query=query,
        target_telegram_id=callback_data.target_telegram_id,
        subscriber_context_page=callback_data.subscriber_context_page,
        linkable_accounts_page_to_show=callback_data.page,
        command_bus=command_bus,
        translator=translator,
    )
    await query.answer()


@tt_account_router.callback_query(LinkTTAccountChosenCallback.filter())
@ensure_message_context
async def link_tt_account_chosen(
    query: CallbackQuery,
    callback_data: LinkTTAccountChosenCallback,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    subscription_service: FromDishka[SubscriptionService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles the selection of a TeamTalk account to link to a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    tt_username = callback_data.tt_username
    return_page = callback_data.page

    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow,
            target_telegram_id,
            "en",  # Language doesn't matter for this operation
        )
        if not user_settings:
            await query.answer(_("Subscriber settings not found."), show_alert=True)
            return

        result = await subscription_service.link_tt_account(
            uow, user_settings, tt_username, translator
        )
        await uow.commit()

    toast_message = _(result.message_key).format(**(result.message_args or {}))
    await query.answer(toast_message, show_alert=not result.success)

    if result.success:
        # Refresh the manage TT account view
        keyboard = create_manage_tt_account_keyboard(
            translator,
            target_telegram_id=target_telegram_id,
            current_tt_username=tt_username,
            page=return_page,
        )
        message_text = _(
            "Manage TeamTalk account link for subscriber {telegram_id}:"
        ).format(telegram_id=target_telegram_id)
        if not query.message:
            logger.error("CallbackQuery message is None in link_tt_account_chosen.")
            await query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
            return

        await edit_message_text(
            message_to_edit=query.message,
            text=message_text,
            reply_markup=keyboard,
        )


@tt_account_router.callback_query(
    ManageTTAccountCallback.filter(F.action == ManageTTAccountAction.UNLINK)
)
@ensure_message_context
async def unlink_tt_account(
    query: CallbackQuery,
    callback_data: ManageTTAccountCallback,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles unlinking a TeamTalk account from a subscriber."""
    _ = translator.gettext
    target_telegram_id = callback_data.target_telegram_id
    return_page = callback_data.page

    async with uow:
        (
            updated_settings,
            original_username,
        ) = await user_settings_service.unlink_tt_account(
            uow, target_telegram_id, actor=Actor.ADMIN
        )
        await uow.commit()

    if not updated_settings:
        await query.answer(
            _("Failed to unlink account. Please try again."), show_alert=True
        )
        return

    if original_username is None:
        await query.answer(_("Account was not linked."), show_alert=False)
        return

    # Обновление интерфейса
    toast_message = _("Account {username} has been unlinked.").format(
        username=original_username
    )
    await query.answer(toast_message, show_alert=True)

    keyboard = create_manage_tt_account_keyboard(
        translator,
        target_telegram_id=target_telegram_id,
        current_tt_username=None,  # Теперь аккаунт отвязан
        page=return_page,
    )
    message_text = _(
        "Manage TeamTalk account link for subscriber {telegram_id}:"
    ).format(telegram_id=target_telegram_id)
    if not query.message:
        logger.error("CallbackQuery message is None in unlink_tt_account.")
        await query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
        return

    await edit_message_text(
        message_to_edit=query.message,
        text=message_text,
        reply_markup=keyboard,
    )
