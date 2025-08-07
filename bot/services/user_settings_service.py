"""Service for managing user-specific settings."""

from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import TypeVar

from bot.core.enums import Actor
from bot.database.uow import IUnitOfWork
from bot.models import MuteListMode, NotificationSetting, UserSettings
from bot.services.cache_service import CacheService
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.utils import update_user_bot_commands

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

    async def get_or_create(self, telegram_id: int, default_lang: str) -> UserSettings:
        """Gets user settings from cache or DB, or creates them if they don't exist."""
        user_settings = self._cache.get_user_settings(telegram_id)
        if user_settings:
            return user_settings

        async with self._uow:
            user_settings = await self._uow.users.get_or_create(
                telegram_id, defaults={"language_code": default_lang}
            )
            await self._uow.commit()

        self._cache.update_user_settings(user_settings)
        return user_settings

    async def _update_setting(
        self,
        user_settings: UserSettings,
        field_name: str,
        new_value: T,
        log_context: str,
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
            return user_settings

        setattr(user_settings, field_name, new_value)
        try:
            async with self._uow:
                await self._uow.users.save(user_settings)
                await self._uow.commit()

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

    async def update_language(
        self,
        bot: EventBot,
        user_settings: UserSettings,
        new_lang_code: str,
        translator_factory: Callable[[str], NullTranslations],
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Updates the language for a user and refreshes their bot commands."""
        log_context = f" by {actor.value}"
        updated_settings = await self._update_setting(
            user_settings, "language_code", new_lang_code, log_context
        )
        if updated_settings:
            new_translator = translator_factory(new_lang_code)
            await update_user_bot_commands(
                telegram_id=user_settings.telegram_id,
                new_lang_code=new_lang_code,
                cache=self._cache,
                bot=bot,
                translator=new_translator,
            )
        return updated_settings

    async def update_mute_mode(
        self,
        user_settings: UserSettings,
        new_mode: MuteListMode,
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Sets the mute list mode for a user."""
        log_context = f" by {actor.value}"
        return await self._update_setting(
            user_settings, "mute_list_mode", new_mode, log_context
        )

    async def update_notification_preference(
        self,
        user_settings: UserSettings,
        new_pref: NotificationSetting,
        actor: Actor = Actor.USER,
    ) -> UserSettings | None:
        """Sets the notification preference for a user."""
        log_context = f" by {actor.value}"
        return await self._update_setting(
            user_settings, "notification_settings", new_pref, log_context
        )

    async def toggle_noon_setting(
        self, user_settings: UserSettings, actor: Actor = Actor.USER
    ) -> UserSettings | None:
        """Toggles the NOON (Not On Online Notifications) setting for a user."""
        new_noon_value = not user_settings.not_on_online_enabled
        log_context = f" by {actor.value} (toggle NOON)"

        updated_settings = await self._update_setting(
            user_settings, "not_on_online_enabled", new_noon_value, log_context
        )

        if not updated_settings:
            return None

        if (
            updated_settings.not_on_online_enabled
            and not updated_settings.not_on_online_confirmed
        ):
            confirm_log_context = f" by {actor.value} (confirm NOON after toggle)"
            confirmed_settings = await self._update_setting(
                user_settings=updated_settings,
                field_name="not_on_online_confirmed",
                new_value=True,
                log_context=confirm_log_context,
            )
            return confirmed_settings or updated_settings

        return updated_settings
