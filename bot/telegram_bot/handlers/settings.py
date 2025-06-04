import logging
from aiogram import Router # Removed html
# Removed Command from aiogram.filters
# Removed Message from aiogram.types
# Removed AsyncSession from sqlalchemy.ext.asyncio

# Removed get_text from bot.localization
from bot.database.models import NotificationSetting, UserSettings as UserSettingsDbModel # Assuming these are still needed
# Removed UserSpecificSettings, update_user_settings_in_db from bot.core.user_settings

# bot.constants imports removed as they are no longer used in this file.

logger = logging.getLogger(__name__)
settings_router = Router(name="settings_router")

# Unused command handlers (cl, mute, unmute, mute_all, unmute_all, toggle_noon, my_noon_status)
# and their helper functions have been removed from this file.

# Existing comment:
# _set_notification_preference and /notify_* commands removed as per subtask.
# The functionality is now handled via the /settings inline keyboard.
