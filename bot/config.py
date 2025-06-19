# bot/config.py
from typing import Any, Literal, Optional

from pydantic import Field, model_validator, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# Допустимые значения для поля GENDER
GenderType = Literal["male", "female", "neutral"]
# Допустимые языки
LangType = Literal["en", "ru"]


class Settings(BaseSettings):
    """
    Класс для управления настройками приложения.
    Загружает переменные из .env файла и проводит их валидацию.
    """

    # --- Telegram ---
    TG_BOT_TOKEN: str
    # Используем AliasChoices, чтобы pydantic-settings искал сначала
    # переменную TELEGRAM_BOT_EVENT_TOKEN, а потом TG_EVENT_TOKEN.
    TG_EVENT_TOKEN: Optional[str] = Field(None, validation_alias=AliasChoices('TELEGRAM_BOT_EVENT_TOKEN', 'TG_EVENT_TOKEN'))
    TG_BOT_MESSAGE_TOKEN: Optional[str] = None
    TG_ADMIN_CHAT_ID: Optional[int] = None

    # --- TeamTalk Connection ---
    # Используем алиасы для соответствия переменным из старого .env.example
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
    # Эти поля не считываются из окружения, а вычисляются после валидации.
    # Мы добавляем им значение по умолчанию, чтобы они были в модели.
    EFFECTIVE_DEFAULT_LANG: LangType = "en"

    # Конфигурация модели: читать из .env файла
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    @model_validator(mode='after')
    def process_settings(self) -> 'Settings':
        """
        Валидатор, который запускается после обработки всех полей.
        Идеально подходит для логики, зависящей от нескольких полей.
        """
        # 1. Логика для TG_EVENT_TOKEN: если он не задан напрямую,
        #    используем значение из TG_BOT_TOKEN.
        if not self.TG_EVENT_TOKEN:
            self.TG_EVENT_TOKEN = self.TG_BOT_TOKEN

        # 2. Финальная проверка: у нас должен быть токен для событий.
        if not self.TG_EVENT_TOKEN:
            raise ValueError("Необходимо установить переменную окружения TG_BOT_TOKEN или TELEGRAM_BOT_EVENT_TOKEN.")

        # 3. Устанавливаем производное поле EFFECTIVE_DEFAULT_LANG
        #    Это заменяет сложную логику, которая была в старом коде.
        #    Валидатор для DEFAULT_LANG уже гарантирует, что значение корректно.
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
