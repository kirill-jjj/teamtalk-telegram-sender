import argparse
import os
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Name of the environment variable that can override the config file path
CONFIG_FILE_ENV_VAR = "APP_CONFIG_FILE_PATH"

def get_config_path_from_args():
    """
    Determines the config file path.
    Priority:
    1. Environment variable APP_CONFIG_FILE_PATH.
    2. --config command-line argument.
    3. Default value '.env'.
    """
    env_config_path = os.getenv(CONFIG_FILE_ENV_VAR)
    if env_config_path:
        return env_config_path

    parser = argparse.ArgumentParser(description="Application Configuration")
    parser.add_argument(
        "--config",
        type=str,
        default=".env",
        help="Path to the configuration file (e.g., .env, prod.env). Defaults to '.env'",
    )
    # Parse known args to allow other arguments (like those from aiogram)
    # without causing an error if sender.py is called directly with them.
    args, _ = parser.parse_known_args()
    return args.config

GenderType = Literal["male", "female", "neutral"]
LangType = Literal["en", "ru"]

class Settings(BaseSettings):
    """
    Application settings management class.
    Loads variables from a .env file and validates them.
    """

    # --- Telegram ---
    TG_EVENT_TOKEN: Optional[str] = Field(None, validation_alias='TELEGRAM_BOT_EVENT_TOKEN')
    TG_BOT_MESSAGE_TOKEN: Optional[str] = None
    TG_ADMIN_CHAT_ID: Optional[int] = None

    # --- TeamTalk Connection ---
    HOSTNAME: str = Field(validation_alias='HOST_NAME')
    PORT: int = 10333
    ENCRYPTED: bool = False
    USERNAME: str = Field(validation_alias='USER_NAME')
    PASSWORD: str
    CHANNEL: str
    CHANNEL_PASSWORD: Optional[str] = None

    # --- Bot Identity ---
    NICKNAME: str = Field(validation_alias='NICK_NAME')
    STATUS_TEXT: str = ""
    CLIENT_NAME: str = "TTTM"
    SERVER_NAME: Optional[str] = None

    # --- Bot Admin ---
    ADMIN_USERNAME: Optional[str] = None

    # --- Functionality ---
    GLOBAL_IGNORE_USERNAMES: Optional[str] = None
    DATABASE_FILE: str = "bot_data.db"
    DEFAULT_LANG: LangType = "en"
    GENDER: GenderType = "neutral"

    # --- Operational Parameters ---
    DEEPLINK_TTL_SECONDS: int = 300  # Lifetime of deeplinks in seconds (e.g., for /sub)
    TT_RECONNECT_RETRY_SECONDS: int = 15 # How often to retry initial connection or full reconnect to TeamTalk
    TT_RECONNECT_CHECK_INTERVAL_SECONDS: int = 10 # Interval to check for TT connection if bot thinks it's disconnected
    ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS: int = 300 # How often to sync the list of online TT users

    # --- Производные поля (не из .env) ---
    EFFECTIVE_DEFAULT_LANG: LangType = "en"

    model_config = SettingsConfigDict(
            env_file=get_config_path_from_args(),
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

        self.EFFECTIVE_DEFAULT_LANG = self.DEFAULT_LANG

        return self

    @field_validator('GENDER', mode='before')
    @classmethod
    def gender_to_lower(cls, v: Any) -> str:
        """Converts GENDER to lowercase before validation."""
        if isinstance(v, str):
            return v.lower()
        return v

app_config = Settings()
