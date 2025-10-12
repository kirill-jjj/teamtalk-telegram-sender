"""Service for moderation actions like banning and muting."""

from gettext import NullTranslations
import logging
from typing import Annotated, TypeVar

from pydantic import ConfigDict, Field, validate_call

from bot.command_bus.bus import CommandBus
from bot.commands import GetAllTeamTalkAccountsCommand, GetAllTeamTalkAccountsResult
from bot.config import Settings  # Added import
from bot.constants import MSG_GENERAL_ERROR
from bot.core.enums import UserListAction
from bot.database.uow import IUnitOfWork
from bot.models import MutedUser, UserSettings
from bot.services.cache_service import CacheService
from bot.services.schemas import (
    OperationResult,
)
from bot.services.subscription_service import SubscriptionService
from bot.telegram_bot.callback_data import ToggleMuteCallback
from bot.utils.pagination import get_item_from_paginated_list

T = TypeVar("T")

logger = logging.getLogger(__name__)


class ModerationService:
    """Service for moderation actions like banning and muting."""

    def __init__(
        self,
        uow: IUnitOfWork,
        subscription_service: SubscriptionService,
        cache: CacheService,
        command_bus: CommandBus,
        settings: Settings,  # Added settings
    ) -> None:
        """Initializes the moderation service."""
        self._uow = uow
        self._subscription_service = subscription_service
        self._cache = cache
        self._command_bus = command_bus
        self._settings = settings

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def ban_subscriber(
        self,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
    ) -> OperationResult:
        """Bans a user by adding them to the ban list."""
        _ = translator.gettext
        async with self._uow:
            user_settings = await self._uow.users.get_by_id(telegram_id)
            tt_username = user_settings.teamtalk_username if user_settings else None

            # Create a single ban entry that links both identifiers
            await self._uow.bans.add_ban(
                telegram_id=telegram_id,
                teamtalk_username=tt_username,  # Pass both telegram_id and tt_username
                reason="Banned by admin",
            )
            await self._uow.commit()

        return OperationResult(
            success=True,
            message_key=_("User {telegram_id} was banned."),
            message_args={"telegram_id": telegram_id, "tt_username": tt_username},
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def unban_subscriber(
        self,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
    ) -> OperationResult:
        """Unbans a subscriber.

        Finds all linked identifiers in the ban list and removes them.
        """
        _ = translator.gettext
        async with self._uow:
            # 1. Find all ban entries for the given telegram_id.
            bans_for_tg_id = await self._uow.bans.get_by_telegram_id(telegram_id)

            # 2. From these entries, collect all associated TeamTalk usernames.
            #    Using a set for automatic deduplication.
            associated_tt_usernames = {
                ban.teamtalk_username for ban in bans_for_tg_id if ban.teamtalk_username
            }

            # 3. Remove all ban entries by telegram_id.
            await self._uow.bans.remove_by_telegram_id(telegram_id)
            logger.info("Removed all ban entries for Telegram ID: %s.", telegram_id)

            # 4. For each found associated TT username, also remove all their bans.
            #    This is necessary in case the username was banned separately.
            for tt_username in associated_tt_usernames:
                await self._uow.bans.remove_by_teamtalk_username(tt_username)
                logger.info(
                    "Removed all ban entries for linked TeamTalk username: '%s'.",
                    tt_username,
                )

            await self._uow.commit()

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
        uow: IUnitOfWork | None = None,  # <-- Принимаем uow
    ) -> OperationResult:
        """Toggles the mute status of a TeamTalk user for a given user."""
        _ = translator.gettext
        active_uow = uow or self._uow  # Используем переданный uow

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
                account = get_item_from_paginated_list(
                    items=result.accounts,
                    sort_key_extractor=lambda acc: acc.username.lower(),
                    page=callback_data.current_page,
                    idx_on_page=callback_data.user_idx,
                )
                if account:
                    username_to_toggle = account.username
        elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
            username_to_toggle = get_item_from_paginated_list(
                items=[
                    muted.muted_teamtalk_username
                    for muted in user_settings.muted_users_list
                ],
                sort_key_extractor=lambda x: x.lower(),
                page=callback_data.current_page,
                idx_on_page=callback_data.user_idx,
            )
        return username_to_toggle

    async def toggle_mute_from_callback(
        self,
        callback_data: ToggleMuteCallback,
        telegram_id: int,
        command_bus: CommandBus,
        translator: NullTranslations,
    ) -> OperationResult:
        """Orchestrates the entire mute/unmute toggle process from a callback."""
        _ = translator.gettext

        async with self._uow:
            user_settings = await self._uow.users.get_by_id(telegram_id)
            if not user_settings:
                logger.warning(
                    "Could not get user settings for user %s in "
                    "toggle_mute_from_callback",
                    telegram_id,
                )
                return OperationResult(success=False, message_key=MSG_GENERAL_ERROR)

            username_to_toggle = await self.get_target_username_for_toggle(
                callback_data, user_settings, command_bus, translator
            )

            if not username_to_toggle:
                logger.warning(
                    "Could not determine username to toggle mute for user %s.",
                    telegram_id,
                )
                return OperationResult(
                    success=False,
                    message_key=_("Error determining user to mute/unmute. Try again."),
                )

            # `async with` сам сделает commit или rollback
            return await self.toggle_mute_status(
                user_settings, username_to_toggle, translator, uow=self._uow
            )
