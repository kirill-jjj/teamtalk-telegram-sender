"""Service for moderation actions like banning and muting."""

from gettext import NullTranslations
import logging

from bot.database.uow import IUnitOfWork
from bot.models import MutedUser, OperationResult, UserSettings
from bot.services.cache_service import CacheService
from bot.services.subscription_service import SubscriptionService
from bot.teamtalk_bot.connection import TeamTalkConnection

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

    async def ban_and_delete_subscriber(
        self,
        telegram_id: int,
        translator: NullTranslations,
        tt_connection: TeamTalkConnection | None,
    ) -> OperationResult:
        """Bans a user and deletes their profile within a single transaction."""
        _ = translator.gettext

        async with self._uow:
            user_settings = await self._uow.users.get_by_id(telegram_id)
            tt_username = user_settings.teamtalk_username if user_settings else None

            # Ban Telegram ID
            await self._uow.bans.add_ban(telegram_id=telegram_id, reason="Banned by admin")
            # Ban TeamTalk username if it exists
            if tt_username:
                await self._uow.bans.add_ban(
                    teamtalk_username=tt_username,
                    reason=f"Linked to banned TG ID {telegram_id}",
                )

            # Delete profile within the same transaction
            await self._subscription_service.delete_profile(telegram_id, uow=self._uow)

            await self._uow.commit()

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
        """Unbans a subscriber by removing all their ban entries."""
        async with self._uow:
            user_settings = await self._uow.users.get_by_id(telegram_id)
            tt_username = user_settings.teamtalk_username if user_settings else None

            # Remove bans by Telegram ID
            await self._uow.bans.remove_by_telegram_id(telegram_id)

            # Remove bans by TeamTalk username
            if tt_username:
                tt_bans = await self._uow.bans.get_by_teamtalk_username(tt_username)
                for ban in tt_bans:
                    await self._uow.bans.delete(ban)

            await self._uow.commit()

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

        async with self._uow:
            await self._uow.users.save(user_settings)
            await self._uow.commit()

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
