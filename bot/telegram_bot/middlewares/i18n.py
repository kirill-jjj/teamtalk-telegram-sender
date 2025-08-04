"""Middleware for handling internationalization (i18n)."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.models import UserSettings
from bot.services_container import Services
from bot.telegram_bot.types.workflow_data import WorkflowData


class I18nMiddleware(BaseMiddleware):
    """This middleware sets up the i18n environment for the handler.

    It must be registered AFTER the UserSettingsMiddleware.
    """

    async def __call__(  # noqa: D102
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        services: Services = data["services"]
        user_settings: UserSettings | None = data.get("user_settings")

        lang_code = user_settings.language_code if user_settings else services.config.general.default_lang

        translator = services.get_translator(lang_code)
        data["translator"] = translator

        return await handler(event, data)
