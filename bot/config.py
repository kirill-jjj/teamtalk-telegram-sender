import sys


def get_env_file_from_args():
    """
    Простая функция для поиска пути к .env файлу в аргументах командной строки.
    Возвращает первый найденный аргумент, заканчивающийся на .env,
    или '.env', если ничего не найдено.
    """
    for arg in sys.argv[1:]:
        if arg.endswith('.env'):
            return arg
    return '.env'

from typing import Any, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

GenderType = Literal["male", "female", "neutral"]
LangType = Literal["en", "ru"]

class Settings(BaseSettings):
    """
    Класс для управления настройками приложения.
    Загружает переменные из .env файла и проводит их валидацию.
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
            env_file=get_env_file_from_args(),
            env_file_encoding='utf-8',
            extra='ignore'
        )

    @model_validator(mode='after')
    def process_settings(self) -> 'Settings':
        """
        Валидатор для проверки взаимозависимых полей.
        """
        if not self.TG_EVENT_TOKEN and self.TG_BOT_TOKEN:
            self.TG_EVENT_TOKEN = self.TG_BOT_TOKEN

        if not self.TG_EVENT_TOKEN:
            raise ValueError("Необходимо установить переменную окружения TG_BOT_TOKEN или TELEGRAM_BOT_EVENT_TOKEN.")

        self.EFFECTIVE_DEFAULT_LANG = self.DEFAULT_LANG

        return self

    @field_validator('GENDER', mode='before')
    @classmethod
    def gender_to_lower(cls, v: Any) -> str:
        """Приводит GENDER к нижнему регистру перед валидацией."""
        if isinstance(v, str):
            return v.lower()
        return v

app_config = Settings()
