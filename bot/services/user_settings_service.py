"""Service for managing user-specific settings."""

import logging
from typing import TypeVar

from pydantic import ConfigDict, validate_call

from bot.core.enums import Actor
from bot.database.uow import IUnitOfWork
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.services.cache_service import CacheService
from bot.services.schemas import (
    AccountManagementData,
    SettingsViewDTO,
    SubscriberViewData,
)
from bot.telegram_bot.api import get_display_name_for_id
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)

T = TypeVar("T")


class UserSettingsService:
    """Service for managing user settings."""

    def __init__(self, uow: IUnitOfWork, cache: CacheService) -> None:
        """Initializes the user settings service.

        Args:
            uow: The unit of work.
            cache: The cache service.
        """
        self._uow = uow
        self._cache = cache

    async def get_user_settings_view(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        default_lang: str,
    ) -> SettingsViewDTO:
        """Gets user settings and maps them to a view DTO."""
        user_settings_model = await self.get_or_create(uow, telegram_id, default_lang)

        return SettingsViewDTO(
            language_code=user_settings_model.language_code,
            notification_settings=user_settings_model.notification_settings,
            mute_list_mode=user_settings_model.mute_list_mode,
            not_on_online_enabled=user_settings_model.not_on_online_enabled,
            teamtalk_username=user_settings_model.teamtalk_username,
            muted_users_count=len(user_settings_model.muted_users_list),
        )

    async def get_subscriber_view_data(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        default_lang: str,
        bot: EventBot,
    ) -> SubscriberViewData | None:
        """Retrieves user settings and their display name."""
        user_settings = await self.get_or_create(uow, telegram_id, default_lang)
        if not user_settings:
            return None

        display_name = await get_display_name_for_id(bot, telegram_id)
        return SubscriberViewData(
            user_settings=user_settings, display_name=display_name
        )

    @staticmethod
    async def get_account_management_data(
        uow: IUnitOfWork, telegram_id: int
    ) -> AccountManagementData:
        """Fetches data needed for the account management view."""
        user_settings = await uow.users.get_by_id(telegram_id)
        return AccountManagementData(
            current_tt_username=user_settings.teamtalk_username
            if user_settings
            else None
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def get_or_create(
        self, uow: IUnitOfWork, telegram_id: int, default_lang: str
    ) -> UserSettings:
        """Gets user settings from cache or DB, or creates them if they don't exist."""
        user_settings = self._cache.get_user_settings(telegram_id)
        if user_settings:
            return user_settings

        user_settings = await uow.users.get_or_create(
            telegram_id, defaults={"language_code": default_lang}
        )

        self._cache.update_user_settings(user_settings)
        return user_settings

    async def _update_setting(
        self,
        user_settings: UserSettings,
        field_name: str,
        new_value: T,
        log_context: str,
        uow: IUnitOfWork | None = None,
    ) -> UserSettings | None:
        """A generic helper to update a field on the UserSettings model."""
        telegram_id = user_settings.telegram_id
        current_value = getattr(user_settings, field_name)

        if current_value == new_value:
            logger.debug(
                "Skipping update for user %s: %s is already '%s'%s.",
                telegram_id,
                field_name,
                new_value,
                log_context,
            )
            return None

        setattr(user_settings, field_name, new_value)
        active_uow = uow or self._uow
        try:
            await active_uow.users.save(user_settings)

            self._cache.update_user_settings(user_settings)
            logger.info(
                "Successfully updated %s for user %s to '%s'%s.",
                field_name,
                telegram_id,
                new_value,
                log_context,
            )
        except Exception:
            logger.exception(
                "Failed to update %s for user %s to '%s'%s.",
                field_name,
                telegram_id,
                new_value,
                log_context,
            )
            # Revert in-memory change on failure
            setattr(user_settings, field_name, current_value)
            return None
        else:
            return user_settings

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def update_language(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        new_lang_code: str,
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Updates the language for a user and refreshes their bot commands."""
        log_context = f" by {actor.value}"
        user_settings = await uow.users.get_by_id(telegram_id)
        if not user_settings:
            logger.error("Could not find user_settings for user %s", telegram_id)
            return None

        return await self._update_setting(
            user_settings,
            "language_code",
            new_lang_code,
            log_context,
            uow=uow,
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def update_mute_mode(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        new_mode: MuteListMode,
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Sets the mute list mode for a user."""
        log_context = f" by {actor.value}"
        user_settings = await uow.users.get_by_id(telegram_id)
        if not user_settings:
            logger.error("Could not find user_settings for user %s", telegram_id)
            return None

        return await self._update_setting(
            user_settings, "mute_list_mode", new_mode, log_context, uow=uow
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def update_notification_preference(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        new_pref: NotificationSetting,
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Sets the notification preference for a user."""
        log_context = f" by {actor.value}"
        user_settings = await uow.users.get_by_id(telegram_id)
        if not user_settings:
            logger.error("Could not find user_settings for user %s", telegram_id)
            return None

        return await self._update_setting(
            user_settings,
            "notification_settings",
            new_pref,
            log_context,
            uow=uow,
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def toggle_noon_setting(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Toggles the NOON (Not On Online Notifications) setting for a user."""
        user_settings = await uow.users.get_by_id(telegram_id)
        if not user_settings:
            logger.error("Could not find user_settings for user %s", telegram_id)
            return None

        new_noon_value = not user_settings.not_on_online_enabled
        log_context = f" by {actor.value} (toggle NOON)"

        updated_settings = await self._update_setting(
            user_settings,
            "not_on_online_enabled",
            new_noon_value,
            log_context,
            uow=uow,
        )

        if not updated_settings:
            return None

        if (
            updated_settings.not_on_online_enabled
            and not user_settings.not_on_online_confirmed
        ):
            confirm_log_context = f" by {actor.value} (confirm NOON after toggle)"
            return await self._update_setting(
                user_settings=user_settings,
                field_name="not_on_online_confirmed",
                new_value=True,
                log_context=confirm_log_context,
                uow=uow,
            )

        return updated_settings

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def unlink_tt_account(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        actor: Actor = Actor.ADMIN,
    ) -> tuple[UserSettings | None, str | None]:
        """Unlinks a TeamTalk account from a user's settings."""
        user_settings = await uow.users.get_by_id(telegram_id)
        if not user_settings:
            return None, None

        original_username = user_settings.teamtalk_username
        if not original_username:
            return user_settings, None

        log_context = f" by {actor.value}"

        updated_settings = await self._update_setting(
            user_settings, "teamtalk_username", None, log_context, uow=uow
        )
        return updated_settings, original_username
