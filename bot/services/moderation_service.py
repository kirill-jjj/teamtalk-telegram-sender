"""Service for moderation actions like banning and muting."""

from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import Annotated, Any, TypeVar

from pydantic import ConfigDict, Field, validate_call

from bot.command_bus.bus import CommandBus
from bot.commands import GetAllTeamTalkAccountsCommand, GetAllTeamTalkAccountsResult
from bot.constants import USERS_PER_PAGE
from bot.core.enums import UserListAction
from bot.database.uow import IUnitOfWork
from bot.models import MutedUser, UserSettings
from bot.services.cache_service import CacheService
from bot.services.schemas import OperationResult
from bot.services.subscription_service import SubscriptionService
from bot.telegram_bot.callback_data import ToggleMuteCallback
from bot.telegram_bot.ui_utils import paginate_list

T = TypeVar("T")

logger = logging.getLogger(__name__)


class ModerationService:
    """Service for moderation actions like banning and muting."""

    def __init__(
        self,
        uow: IUnitOfWork,
        subscription_service: SubscriptionService,
        cache: CacheService,
    ) -> None:
        """Initializes the moderation service."""
        self._uow = uow
        self._subscription_service = subscription_service
        self._cache = cache

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def ban_and_delete_subscriber(
        self,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
        uow: IUnitOfWork | None = None,
    ) -> OperationResult:
        """Bans a user and deletes their profile within a single transaction."""
        _ = translator.gettext
        active_uow = uow or self._uow

        user_settings = await active_uow.users.get_by_id(telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        # Create a single ban entry that links both identifiers
        await active_uow.bans.add_ban(
            telegram_id=telegram_id,
            teamtalk_username=tt_username,  # Pass both telegram_id and tt_username
            reason="Banned by admin",
        )

        # Delete profile within the same transaction
        await self._subscription_service.delete_profile(
            telegram_id, translator, uow=active_uow
        )

        return OperationResult(
            success=True,
            message_key=_(
                "User {telegram_id} was banned and their profile was deleted."
            ),
            message_args={"telegram_id": telegram_id, "tt_username": tt_username},
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def unban_subscriber(
        self,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
        uow: IUnitOfWork | None = None,
    ) -> OperationResult:
        """Unbans a subscriber.

        Finds all linked identifiers in the ban list and removes them.
        """
        _ = translator.gettext
        active_uow = uow or self._uow

        # 1. Find all ban entries for the given telegram_id.
        bans_for_tg_id = await active_uow.bans.get_by_telegram_id(telegram_id)

        # 2. From these entries, collect all associated TeamTalk usernames.
        #    Using a set for automatic deduplication.
        associated_tt_usernames = {
            ban.teamtalk_username for ban in bans_for_tg_id if ban.teamtalk_username
        }

        # 3. Remove all ban entries by telegram_id.
        await active_uow.bans.remove_by_telegram_id(telegram_id)
        logger.info("Removed all ban entries for Telegram ID: %s.", telegram_id)

        # 4. For each found associated TT username, also remove all their bans.
        #    This is necessary in case the username was banned separately.
        for tt_username in associated_tt_usernames:
            await active_uow.bans.remove_by_teamtalk_username(tt_username)
            logger.info(
                "Removed all ban entries for linked TeamTalk username: '%s'.",
                tt_username,
            )

        logger.info(
            "Successfully unbanned user %s and all associated accounts.", telegram_id
        )
        # Message for the user in .po files
        # msgid "unban_success"
        # msgstr "User {telegram_id} was successfully unbanned."
        return OperationResult(
            success=True,
            message_key=_("User has been successfully unbanned."),
            message_args={"telegram_id": telegram_id},
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def toggle_mute_status(
        self,
        user_settings: UserSettings,
        tt_username_to_toggle: str,
        translator: NullTranslations,
        uow: IUnitOfWork | None = None,
    ) -> OperationResult:
        """Toggles the mute status of a TeamTalk user for a given user."""
        _ = translator.gettext
        active_uow = uow or self._uow
        existing_entry = next(
            (
                entry
                for entry in user_settings.muted_users_list
                if entry.muted_teamtalk_username == tt_username_to_toggle
            ),
            None,
        )

        if existing_entry:
            user_settings.muted_users_list.remove(existing_entry)
            action = "unmuted"
        else:
            new_entry = MutedUser(
                user_settings_telegram_id=user_settings.telegram_id,
                muted_teamtalk_username=tt_username_to_toggle,
            )
            user_settings.muted_users_list.append(new_entry)
            action = "muted"

        await active_uow.users.save(user_settings)

        self._cache.update_user_settings(user_settings)

        logger.info(
            "Successfully %s TT user '%s' for TG user %s.",
            action,
            tt_username_to_toggle,
            user_settings.telegram_id,
        )
        message_text = (
            _("User {username} has been successfully muted.")
            if action == "muted"
            else _("User {username} has been successfully unmuted.")
        )
        return OperationResult(
            success=True,
            message_key=message_text,
            message_args={"username": tt_username_to_toggle},
            user_settings=user_settings,
        )

    def _get_item_from_paginated_list(
        self,
        items: list[T],
        sort_key_extractor: Callable[[T], Any],
        page: int,
        idx_on_page: int,
    ) -> T | None:
        """Gets a specific item from a paginated list."""
        sorted_items = sorted(items, key=sort_key_extractor)
        page_items, _, _ = paginate_list(sorted_items, page, USERS_PER_PAGE)
        if 0 <= idx_on_page < len(page_items):
            return page_items[idx_on_page]
        return None

    async def get_target_username_for_toggle(
        self,
        callback_data: ToggleMuteCallback,
        user_settings: UserSettings,
        command_bus: CommandBus,
        translator: NullTranslations,
    ) -> str | None:
        """Determines the username to toggle mute status for based on callback data."""
        _ = translator.gettext
        username_to_toggle = None
        list_type = callback_data.list_type

        if list_type == UserListAction.LIST_ALL_ACCOUNTS:
            result: GetAllTeamTalkAccountsResult = await command_bus.execute(
                GetAllTeamTalkAccountsCommand(
                    lang_code=translator.info().get("language", "en")
                )
            )
            if result.success:
                account = self._get_item_from_paginated_list(
                    items=result.accounts,
                    sort_key_extractor=lambda acc: acc.username.lower(),
                    page=callback_data.current_page,
                    idx_on_page=callback_data.user_idx,
                )
                if account:
                    username_to_toggle = account.username
        elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
            username_to_toggle = self._get_item_from_paginated_list(
                items=[
                    muted.muted_teamtalk_username
                    for muted in user_settings.muted_users_list
                ],
                sort_key_extractor=lambda x: x.lower(),
                page=callback_data.current_page,
                idx_on_page=callback_data.user_idx,
            )
        return username_to_toggle
