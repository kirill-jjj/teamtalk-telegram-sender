from typing import Any, Optional, Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from bot.core.languages import DEFAULT_LANGUAGE_CODE

GenderType = Literal["male", "female", "neutral"]

class Settings(BaseSettings):
    """
    Application settings management class.
    Loads variables from a .env file and validates them.
    """

    TG_EVENT_TOKEN: Optional[str] = Field(None, validation_alias='TELEGRAM_BOT_EVENT_TOKEN')
    TG_BOT_MESSAGE_TOKEN: Optional[str] = None
    TG_ADMIN_CHAT_ID: Optional[int] = None

    HOSTNAME: str = Field(validation_alias='HOST_NAME')
    PORT: int = 10333
    ENCRYPTED: bool = False
    USERNAME: str = Field(validation_alias='USER_NAME')
    PASSWORD: str
    CHANNEL: str
    CHANNEL_PASSWORD: Optional[str] = None

    NICKNAME: str = Field(validation_alias='NICK_NAME')
    STATUS_TEXT: str = ""
    CLIENT_NAME: str = "TTTM"
    SERVER_NAME: Optional[str] = None

    ADMIN_USERNAME: Optional[str] = None

    GLOBAL_IGNORE_USERNAMES: Optional[str] = None
    DATABASE_FILE: str = "bot_data.db"
    DEFAULT_LANG: str = DEFAULT_LANGUAGE_CODE
    GENDER: GenderType = "neutral"

    DEEPLINK_TTL_SECONDS: int = 300  # Lifetime of deeplinks in seconds (e.g., for /sub)
    TT_RECONNECT_RETRY_SECONDS: int = 15 # How often to retry initial connection or full reconnect to TeamTalk
    TT_RECONNECT_CHECK_INTERVAL_SECONDS: int = 10 # Interval to check for TT connection if bot thinks it's disconnected
    ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS: int = 300 # How often to sync the list of online TT users

    model_config = SettingsConfigDict(
            env_file=".env",  # Default value if _env_file is not provided
            env_file_encoding='utf-8',
            extra='ignore'
        )

    @model_validator(mode='after')
    def process_settings(self) -> 'Settings':
        """
        Validator for checking interdependent fields.
        """
        if not self.TG_EVENT_TOKEN:
            raise ValueError("The TELEGRAM_BOT_EVENT_TOKEN environment variable must be set.")

        return self

    @field_validator('GENDER', mode='before')
    @classmethod
    def gender_to_lower(cls, v: Any) -> str:
        """Converts GENDER to lowercase before validation."""
        if isinstance(v, str):
            return v.lower()
        return v
