# bot/config.py
from typing import Any, Literal, Optional

from pydantic import Field, model_validator, field_validator # AliasChoices removed
from pydantic_settings import BaseSettings, SettingsConfigDict

# Допустимые значения для полей
GenderType = Literal["male", "female", "neutral"]
LangType = Literal["en", "ru"]

class Settings(BaseSettings):
    """
    Класс для управления настройками приложения.
    Загружает переменные из .env файла и проводит их валидацию.
    """

    # --- Telegram ---
    # ИЗМЕНЕНИЕ 1: Оба токена теперь опциональны на уровне полей.
    # Обязательность мы проверим в @model_validator.
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

    # Конфигурация модели: читать из .env файла
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    @model_validator(mode='after')
    def process_settings(self) -> 'Settings':
        """
        Валидатор для проверки взаимозависимых полей.
        """
        # ИЗМЕНЕНИЕ 2: Обновленная, более надежная логика валидации токенов.
        # Сначала пытаемся заполнить TG_EVENT_TOKEN из TG_BOT_TOKEN, если первый не задан.
        if not self.TG_EVENT_TOKEN and self.TG_BOT_TOKEN:
            self.TG_EVENT_TOKEN = self.TG_BOT_TOKEN

        # Теперь проверяем, что в итоге у нас есть токен для событий.
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


# Создаем единственный экземпляр настроек для всего приложения
app_config = Settings()
