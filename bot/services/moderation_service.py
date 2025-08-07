"""Service for moderation actions like banning and muting."""

from gettext import NullTranslations
import logging

from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.user_repository import UserRepository
from bot.models import MutedUser, OperationResult, UserSettings
from bot.services.cache_service import CacheService
from bot.services.subscription_service import SubscriptionService
from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)


class ModerationService:
    """Service for moderation actions like banning and muting."""

    def __init__(
        self,
        ban_repo: BanRepository,
        user_repo: UserRepository,
        subscription_service: SubscriptionService,
        cache: CacheService,
    ) -> None:
        """Initializes the moderation service."""
        self._ban_repo = ban_repo
        self._user_repo = user_repo
        self._subscription_service = subscription_service
        self._cache = cache

    async def ban_and_delete_subscriber(
        self,
        telegram_id: int,
        translator: NullTranslations,
        tt_connection: TeamTalkConnection | None,
    ) -> OperationResult:
        """Bans a user and deletes their profile.

        Args:
            telegram_id: The Telegram ID of the user to ban.
            translator: The translator for localization.
            tt_connection: The active TeamTalk connection, if any.

        Returns:
            An OperationResult detailing the outcome.
        """
        _ = translator.gettext
        user_settings = await self._user_repo.get_by_id(telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        # Ban Telegram ID
        await self._ban_repo.add_ban(telegram_id=telegram_id, reason="Banned by admin")
        # Ban TeamTalk username if it exists
        if tt_username:
            await self._ban_repo.add_ban(
                teamtalk_username=tt_username,
                reason=f"Linked to banned TG ID {telegram_id}",
            )

        # Delete profile
        await self._subscription_service.delete_profile(telegram_id)

        # Conceptual server moderation
        if tt_username and tt_connection:
            logger.info(
                "Conceptual TT server ban for '%s' (TG ID %s).",
                tt_username,
                telegram_id,
            )

        return OperationResult(
            success=True,
            message_key=_("ban_success_full"),
            message_args={"telegram_id": telegram_id, "tt_username": tt_username},
        )

    async def unban_subscriber(self, telegram_id: int) -> OperationResult:
        """Unbans a subscriber by removing all their ban entries.

        Args:
            telegram_id: The Telegram ID of the user to unban.

        Returns:
            An OperationResult detailing the outcome.
        """
        user_settings = await self._user_repo.get_by_id(telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        # Remove bans by Telegram ID
        await self._ban_repo.remove_by_telegram_id(telegram_id)

        # Remove bans by TeamTalk username
        if tt_username:
            tt_bans = await self._ban_repo.get_by_teamtalk_username(tt_username)
            for ban in tt_bans:
                await self._ban_repo.delete(ban)

        logger.info("Successfully unbanned user %s.", telegram_id)
        return OperationResult(
            success=True,
            message_key="unban_success",
            message_args={"telegram_id": telegram_id},
        )

    async def toggle_mute_status(
        self,
        user_settings: UserSettings,
        tt_username_to_toggle: str,
        translator: NullTranslations,
    ) -> OperationResult:
        """Toggles the mute status of a TeamTalk user for a given user.

        Args:
            user_settings: The settings of the user toggling the mute.
            tt_username_to_toggle: The TeamTalk username to mute/unmute.
            translator: The translator for localization.

        Returns:
            An OperationResult detailing the outcome.
        """
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

        await self._user_repo.save(user_settings)
        self._cache.update_user_settings(user_settings)

        logger.info(
            "Successfully %s TT user '%s' for TG user %s.",
            action,
            tt_username_to_toggle,
            user_settings.telegram_id,
        )
        message_key = (
            _("mute_toggle_success_muted")
            if action == "muted"
            else _("mute_toggle_success_unmuted")
        )
        return OperationResult(
            success=True,
            message_key=message_key,
            message_args={"username": tt_username_to_toggle},
            user_settings=user_settings,
        )
