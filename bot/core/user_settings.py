import asyncio
import logging
from typing import Any, Union

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import app_config
from bot.database.crud import add_subscriber
from bot.database.models import (  # Assuming NotificationSetting is an Enum or similar
    NotificationSetting,
    UserSettings,
)

logger = logging.getLogger(__name__)

class UserSpecificSettings(BaseModel):
    language: str = Field(default_factory=lambda: app_config.EFFECTIVE_DEFAULT_LANG)
    notification_settings: NotificationSetting = NotificationSetting.ALL
    muted_users_set: set[str] = Field(default_factory=set, alias="muted_users")
    mute_all_flag: bool = Field(default=False, alias="mute_all")
    teamtalk_username: Union[str, None] = None # Using Union for Optional fields
    not_on_online_enabled: bool = False
    not_on_online_confirmed: bool = False

    @field_validator("muted_users_set", mode="before")
    @classmethod
    def _split_muted_users_string(cls, value: Any) -> set[str]:
        if isinstance(value, str):
            if not value: # Handle empty string
                return set()
            return set(value.split(","))
        if isinstance(value, set):
            return value
        return set() # Default to empty set if type is unexpected

    class Config:
        from_attributes = True
        populate_by_name = True # To allow using aliases during initialization

def _prepare_muted_users_string(users_set: set[str]) -> str:
    if not users_set:
        return ""
    return ",".join(sorted(list(users_set)))

USER_SETTINGS_CACHE: dict[int, UserSpecificSettings] = {}

async def load_user_settings_to_cache(session_factory) -> None:
    logger.info("Loading user settings into cache...")
    async with session_factory() as session:
        result = await session.execute(select(UserSettings))
        user_settings_list = result.scalars().all()
        for settings_row in user_settings_list:
            try:
                # Pass the row directly, Pydantic will map columns to fields
                # The alias "muted_users" in the model will map to settings_row.muted_users
                USER_SETTINGS_CACHE[settings_row.telegram_id] = UserSpecificSettings.model_validate(settings_row)
            except Exception as e:
                logger.error(f"Failed to validate settings for user {settings_row.telegram_id} from DB: {e}", exc_info=True)
    logger.debug(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")

async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSpecificSettings:
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    user_settings_row = await session.get(UserSettings, telegram_id)
    if user_settings_row:
        try:
            specific_settings = UserSpecificSettings.model_validate(user_settings_row)
            USER_SETTINGS_CACHE[telegram_id] = specific_settings
            return specific_settings
        except Exception as e:
            logger.error(f"Failed to validate existing settings for user {telegram_id} from DB: {e}", exc_info=True)
            # Fallback to default if validation fails for existing settings
            default_settings = UserSpecificSettings()
            USER_SETTINGS_CACHE[telegram_id] = default_settings
            return default_settings
    else:
        # For new users, create settings with default values from the Pydantic model
        default_settings = UserSpecificSettings()

        # Dump model to dict, Pydantic handles aliases correctly for DB fields
        settings_dict_for_db = default_settings.model_dump(by_alias=True)

        # The validator for muted_users_set expects a string or set,
        # model_dump by default gives a set. We need to convert it to string for DB.
        settings_dict_for_db["muted_users"] = await asyncio.to_thread(
            _prepare_muted_users_string, default_settings.muted_users_set
        )

        # Remove fields not in UserSettings DB model or adapt as necessary
        # For example, if UserSettings model doesn't have 'muted_users_set' but 'muted_users'
        # and 'mute_all_flag' but 'mute_all'
        # model_dump(by_alias=True) should handle this.
        # We manually handled muted_users above, ensure other fields match DB columns.

        new_settings_row_data = {
            "telegram_id": telegram_id,
            "language": default_settings.language,
            "notification_settings": default_settings.notification_settings,
            "muted_users": settings_dict_for_db["muted_users"], # Use the prepared string
            "mute_all": default_settings.mute_all_flag, # Uses alias if defined in model_dump, direct access otherwise
            "teamtalk_username": default_settings.teamtalk_username,
            "not_on_online_enabled": default_settings.not_on_online_enabled,
            "not_on_online_confirmed": default_settings.not_on_online_confirmed,
        }

        new_settings_row = UserSettings(**new_settings_row_data)
        session.add(new_settings_row)
        try:
            await session.commit()
            logger.debug(f"Created default UserSettings row for user {telegram_id} in DB.")
            USER_SETTINGS_CACHE[telegram_id] = default_settings

            if default_settings.notification_settings != NotificationSetting.NONE:
                if await add_subscriber(session, telegram_id):
                    logger.info(f"User {telegram_id} automatically subscribed due to default notification settings.")
                else:
                    logger.warning(f"Failed to automatically subscribe user {telegram_id} on settings creation.")
            return default_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}", exc_info=True)
            # Return a default Pydantic instance even if DB save fails
            cached_default = UserSpecificSettings()
            USER_SETTINGS_CACHE[telegram_id] = cached_default # Cache this instance
            return cached_default


async def update_user_settings_in_db(session: AsyncSession, telegram_id: int, settings: UserSpecificSettings):
    user_settings_row = await session.get(UserSettings, telegram_id)
    if not user_settings_row:
        # This case should ideally be handled by get_or_create_user_settings first
        # or we create a new one here if absolutely necessary.
        logger.warning(f"Attempted to update settings for non-existent user {telegram_id}. Creating new row.")
        user_settings_row = UserSettings(telegram_id=telegram_id)
        session.add(user_settings_row)

    # Update the row from the Pydantic model
    # model_dump ensures we get values compatible with DB (e.g. enums converted to their values if configured)
    update_data = settings.model_dump(by_alias=True) # Use by_alias to get 'muted_users' and 'mute_all'

    user_settings_row.language = update_data.get("language", app_config.EFFECTIVE_DEFAULT_LANG)
    user_settings_row.notification_settings = update_data.get("notification_settings", NotificationSetting.ALL)

    # Special handling for muted_users_set to convert set to string
    user_settings_row.muted_users = await asyncio.to_thread(_prepare_muted_users_string, settings.muted_users_set)

    user_settings_row.mute_all = update_data.get("mute_all", False) # Direct access or .get for fields with aliases
    user_settings_row.teamtalk_username = update_data.get("teamtalk_username")
    user_settings_row.not_on_online_enabled = update_data.get("not_on_online_enabled", False)
    user_settings_row.not_on_online_confirmed = update_data.get("not_on_online_confirmed", False)

    try:
        await session.commit()
        USER_SETTINGS_CACHE[telegram_id] = settings # Cache the Pydantic model instance
        logger.debug(f"Updated settings for user {telegram_id} in DB and cache.")
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {telegram_id} in DB: {e}", exc_info=True)

# Ensure app_config is loaded for default_factory in Pydantic model
if not app_config.EFFECTIVE_DEFAULT_LANG:
    logger.warning("app_config.EFFECTIVE_DEFAULT_LANG is not set. Pydantic default_factory might fail.")
