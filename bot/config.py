import argparse
from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def get_config_path_from_args():
    """
    Parses command line arguments to get the path to the config file.
    Defaults to '.env' if no path is provided.
    """
    parser = argparse.ArgumentParser(description="Bot Configuration")
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
    TG_BOT_TOKEN: Optional[str] = None
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
        if not self.TG_EVENT_TOKEN and self.TG_BOT_TOKEN:
            self.TG_EVENT_TOKEN = self.TG_BOT_TOKEN

        if not self.TG_EVENT_TOKEN:
            raise ValueError("The TG_BOT_TOKEN or TELEGRAM_BOT_EVENT_TOKEN environment variable must be set.")

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
