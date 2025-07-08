# bot/services/cache_service.py

import logging
from typing import TYPE_CHECKING
from bot.models import UserSettings

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self, services: "Services"):
        self._services = services
        # Direct access for convenience within this service
        self._user_settings_cache = services.user_settings_cache
        self._admin_ids_cache = services.admin_ids_cache
        self._subscribed_users_cache = services.subscribed_users_cache

    # --- Methods for admins ---
    def add_admin(self, telegram_id: int):
        self._admin_ids_cache.add(telegram_id)
        logger.debug("Admin %s added to cache.", telegram_id)

    def remove_admin(self, telegram_id: int):
        self._admin_ids_cache.discard(telegram_id)
        logger.debug("Admin %s removed from cache.", telegram_id)

    def is_admin(self, telegram_id: int) -> bool:
        # This method is for checking, so direct read is fine and doesn't need to be part of this refactor's scope
        # as the prompt focuses on modification operations.
        # However, to keep consistency, we can route it via the service.
        return telegram_id in self._admin_ids_cache

    def load_admins_from_db(self, admin_ids: list[int]):
        self._admin_ids_cache.clear() # Clear before loading to ensure consistency
        self._admin_ids_cache.update(admin_ids)
        logger.info("Admin cache populated with %d IDs.", len(admin_ids))

    def get_all_admin_ids(self) -> set[int]:
        return self._admin_ids_cache.copy() # Return a copy to prevent external modification

    def get_admin_count(self) -> int:
        return len(self._admin_ids_cache)

    # --- Methods for subscribers ---
    def add_subscriber(self, telegram_id: int):
        self._subscribed_users_cache.add(telegram_id)
        logger.debug("Subscriber %s added to cache.", telegram_id)

    def remove_subscriber(self, telegram_id: int):
        self._subscribed_users_cache.discard(telegram_id)
        logger.debug("Subscriber %s removed from cache.", telegram_id)

    def is_subscribed(self, telegram_id: int) -> bool:
        # Similar to is_admin, read operations can be direct but routed for consistency.
        return telegram_id in self._subscribed_users_cache

    def load_subscribers_from_db(self, subscriber_ids: list[int]):
        self._subscribed_users_cache.clear() # Clear before loading
        self._subscribed_users_cache.update(subscriber_ids)
        logger.info("Subscriber cache populated with %d IDs.", len(subscriber_ids))

    def get_all_subscriber_ids(self) -> set[int]:
        return self._subscribed_users_cache.copy() # Return a copy

    # --- Methods for user settings ---
    def get_user_settings(self, telegram_id: int) -> UserSettings | None:
        return self._user_settings_cache.get(telegram_id)

    def update_user_settings(self, settings: UserSettings):
        """Updates or adds user settings in the cache."""
        if not isinstance(settings, UserSettings):
            logger.error("Attempted to update cache with non-UserSettings object: %s", type(settings))
            return
        self._user_settings_cache[settings.telegram_id] = settings
        logger.debug("User settings for %s updated in cache.", settings.telegram_id)

    def remove_user_settings(self, telegram_id: int):
        if telegram_id in self._user_settings_cache:
            del self._user_settings_cache[telegram_id]
            logger.debug("User settings for %s removed from cache.", telegram_id)
        else:
            logger.debug("Attempted to remove user settings for %s, but user was not in cache.", telegram_id)


    def load_all_user_settings(self, all_settings: list[UserSettings]):
        self._user_settings_cache.clear() # Clear before loading
        for setting in all_settings:
            if not isinstance(setting, UserSettings):
                logger.warning("Skipping non-UserSettings object during bulk load: %s", type(setting))
                continue
            self._user_settings_cache[setting.telegram_id] = setting
        logger.info("Loaded %s user settings into cache.", len(self._user_settings_cache))

    # --- Comprehensive operations ---
    def remove_full_user_profile(self, telegram_id: int):
        """Removes a user from all relevant caches."""
        self.remove_admin(telegram_id)
        self.remove_subscriber(telegram_id)
        self.remove_user_settings(telegram_id)
        logger.info("Full user profile for %s removed from all caches via CacheService.", telegram_id)
