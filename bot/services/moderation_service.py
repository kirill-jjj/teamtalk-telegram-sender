"""Service for moderation actions like banning and muting."""

from gettext import NullTranslations
from html import escape
import logging
from typing import Annotated, TypeVar

from pydantic import ConfigDict, Field, validate_call
from pytalk.exceptions import PytalkPermissionError
from pytalk.exceptions import TeamTalkError as PytalkException

from bot.config import Settings
from bot.core.enums import AdminCommand, UserListAction
from bot.database.models import MutedUser, UserSettings
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.schemas import OperationResult
from bot.services.subscription_service import SubscriptionService
from bot.services.teamtalk_service import TeamTalkService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.formatters import (
    get_server_display_name,
    get_tt_user_display_name,
)
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
        settings: Settings,
        tt_connection: TeamTalkConnection,
        teamtalk_service: TeamTalkService,
    ) -> None:
        """Initializes the moderation service."""
        self._uow = uow
        self._subscription_service = subscription_service
        self._cache = cache
        self._settings = settings
        self._tt_connection = tt_connection
        self._teamtalk_service = teamtalk_service

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def ban_subscriber(
        self,
        uow: IUnitOfWork,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
    ) -> OperationResult:
        """Bans a user by adding them to the ban list and deleting their profile."""
        _ = translator.gettext
        user_settings = await uow.users.get_by_id(telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        # Create a single ban entry that links both identifiers
        await uow.bans.add_ban(
            telegram_id=telegram_id,
            teamtalk_username=tt_username,  # Pass both telegram_id and tt_username
            reason="Banned by admin",
        )
        logger.info(
            "User %s (TT username: '%s') added to the ban list.",
            telegram_id,
            tt_username,
        )

        # After banning, completely delete the user's profile
        await self._subscription_service.delete_profile(uow, telegram_id, translator)
        logger.info("User %s profile deleted as part of the ban process.", telegram_id)

        return OperationResult(
            success=True,
            message_key=_(
                "User {telegram_id} was banned and their profile was deleted."
            ),
            message_args={"telegram_id": telegram_id, "tt_username": tt_username},
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def unban_subscriber(  # noqa: PLR6301
        self,
        uow: IUnitOfWork,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
    ) -> OperationResult:
        """Unbans a subscriber.

        Finds all linked identifiers in the ban list and removes them.
        """
        _ = translator.gettext
        # 1. Find all ban entries for the given telegram_id.
        bans_for_tg_id = await uow.bans.get_by_telegram_id(telegram_id)

        # 2. From these entries, collect all associated TeamTalk usernames.
        #    Using a set for automatic deduplication.
        associated_tt_usernames = {
            ban.teamtalk_username for ban in bans_for_tg_id if ban.teamtalk_username
        }

        # 3. Remove all ban entries by telegram_id.
        await uow.bans.remove_by_telegram_id(telegram_id)
        logger.info("Removed all ban entries for Telegram ID: %s.", telegram_id)

        # 4. For each found associated TT username, also remove all their bans.
        #    This is necessary in case the username was banned separately.
        for tt_username in associated_tt_usernames:
            await uow.bans.remove_by_teamtalk_username(tt_username)
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
    async def kick_user_from_server(
        self,
        user_id: int,
        admin_telegram_id: int,
        translator: NullTranslations,
    ) -> OperationResult:
        """Kicks a user from the TeamTalk server."""
        return await self._apply_moderation_action(
            user_id=user_id,
            admin_telegram_id=admin_telegram_id,
            action=AdminCommand.KICK,
            translator=translator,
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def ban_user_from_server(
        self,
        user_id: int,
        admin_telegram_id: int,
        translator: NullTranslations,
    ) -> OperationResult:
        """Bans a user from the TeamTalk server."""
        return await self._apply_moderation_action(
            user_id=user_id,
            admin_telegram_id=admin_telegram_id,
            action=AdminCommand.BAN,
            translator=translator,
        )

    async def _apply_moderation_action(
        self,
        user_id: int,
        admin_telegram_id: int,
        action: AdminCommand,
        translator: NullTranslations,
    ) -> OperationResult:
        """Generic method to apply kick or ban."""
        _ = translator.gettext
        if not self._tt_connection or not self._tt_connection.instance:
            return OperationResult(
                success=False, message_key=_("Error: No active TeamTalk connection.")
            )

        user_to_act_on = self._tt_connection.instance.get_user(user_id)
        server_name_for_display = get_server_display_name(
            self._tt_connection.instance, translator, self._settings
        )

        if not user_to_act_on:
            msg = _("User not found on server {server_host} anymore.").format(
                server_host=server_name_for_display
            )
            return OperationResult(success=False, message_key=msg)

        user_nickname = get_tt_user_display_name(user_to_act_on, translator)

        try:
            if action == AdminCommand.KICK:
                user_to_act_on.kick(from_server=True)
                logger.info(
                    "Admin %s kicked TT user '%s' (ID: %s)",
                    admin_telegram_id,
                    user_nickname,
                    user_id,
                )
                msg = _(
                    "User {user_nickname} kicked from server {server_host}."
                ).format(
                    user_nickname=escape(user_nickname),
                    server_host=server_name_for_display,
                )
                return OperationResult(success=True, message_key=msg)
            if action == AdminCommand.BAN:
                user_to_act_on.ban(from_server=True)
                user_to_act_on.kick(from_server=True)
                logger.info(
                    "Admin %s banned and kicked TT user '%s' (ID: %s)",
                    admin_telegram_id,
                    user_nickname,
                    user_id,
                )
                msg = _(
                    "User {user_nickname} banned and kicked from server {server_host}."
                ).format(
                    user_nickname=escape(user_nickname),
                    server_host=server_name_for_display,
                )
                return OperationResult(success=True, message_key=msg)
        except (PytalkPermissionError, PytalkException):
            logger.exception("Error during '%s' on TT user ID %s", action, user_id)
            return OperationResult(
                success=False,
                message_key=_("An error occurred. Please try again later."),
            )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def toggle_mute_status(
        self,
        uow: IUnitOfWork,
        user_settings: UserSettings,
        tt_username_to_toggle: str,
        translator: NullTranslations,
    ) -> OperationResult:
        """Toggles the mute status of a TeamTalk user for a given user."""
        _ = translator.gettext

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

        await uow.users.save(user_settings)

        self._cache.update_user_settings(user_settings)

        logger.debug(
            "User %s %s TT user '%s'.",
            user_settings.telegram_id,
            action,
            tt_username_to_toggle,
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
        list_type: UserListAction,
        page: int,
        index_on_page: int,
        user_settings: UserSettings,
        translator: NullTranslations,
    ) -> str | None:
        """Determines the username to toggle mute status for based on list context."""
        _ = translator.gettext
        username_to_toggle = None

        if list_type == UserListAction.LIST_ALL_ACCOUNTS:
            result = await self._teamtalk_service.fetch_all_accounts(
                lang_code=translator.info().get("language", "en")
            )
            if not result.error_message:
                account = get_item_from_paginated_list(
                    items=result.items,
                    sort_key_extractor=lambda acc: acc.username.lower(),
                    page=page,
                    idx_on_page=index_on_page,
                )
                if account:
                    username_to_toggle = account.username
        elif list_type in {UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED}:
            username_to_toggle = get_item_from_paginated_list(
                items=[
                    muted.muted_teamtalk_username
                    for muted in user_settings.muted_users_list
                ],
                sort_key_extractor=lambda x: x.lower(),
                page=page,
                idx_on_page=index_on_page,
            )
        return username_to_toggle

    async def toggle_mute_from_paginated_list(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        list_type: UserListAction,
        page: int,
        index_on_page: int,
        translator: NullTranslations,
    ) -> OperationResult:
        """Toggles a user's mute status based on an action from a paginated list."""
        _ = translator.gettext

        user_settings = await uow.users.get_by_id(telegram_id)
        if not user_settings:
            logger.warning(
                "Could not get user settings for user %s in "
                "toggle_mute_from_paginated_list",
                telegram_id,
            )
            return OperationResult(
                success=False,
                message_key=_("An error occurred. Please try again later."),
            )

        username_to_toggle = await self.get_target_username_for_toggle(
            list_type=list_type,
            page=page,
            index_on_page=index_on_page,
            user_settings=user_settings,
            translator=translator,
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

        return await self.toggle_mute_status(
            uow,
            user_settings,
            username_to_toggle,
            translator,
        )
