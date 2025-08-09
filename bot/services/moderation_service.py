"""Service for moderation actions like banning and muting."""

from gettext import NullTranslations
import logging
from typing import Annotated

from pydantic import ConfigDict, Field, validate_call

from bot.database.uow import IUnitOfWork
from bot.models import MutedUser, UserSettings
from bot.services.cache_service import CacheService
from bot.services.schemas import OperationResult
from bot.services.subscription_service import SubscriptionService

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

        # Ban Telegram ID
        await active_uow.bans.add_ban(telegram_id=telegram_id, reason="Banned by admin")
        # Ban TeamTalk username if it exists
        if tt_username:
            await active_uow.bans.add_ban(
                teamtalk_username=tt_username,
                reason=f"Linked to banned TG ID {telegram_id}",
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
        """Unbans a subscriber by removing all their ban entries."""
        _ = translator.gettext
        active_uow = uow or self._uow

        # 1. Find all bans associated with this Telegram ID
        bans_by_tg_id = await active_uow.bans.get_by_telegram_id(telegram_id)

        # 2. Collect all associated TeamTalk usernames from these bans
        associated_tt_usernames = {
            ban.teamtalk_username for ban in bans_by_tg_id if ban.teamtalk_username
        }

        # 3. Remove all bans by Telegram ID
        await active_uow.bans.remove_by_telegram_id(telegram_id)

        # 4. Remove all bans for each found TeamTalk username
        for tt_username in associated_tt_usernames:
            tt_bans = await active_uow.bans.get_by_teamtalk_username(tt_username)
            for ban in tt_bans:
                await active_uow.bans.delete(ban)

        logger.info("Successfully unbanned user %s.", telegram_id)
        return OperationResult(
            success=True,
            message_key=_("Successfully unbanned user {telegram_id}."),
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
