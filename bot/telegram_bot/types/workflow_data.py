"""TypedDict for middleware and handler workflow data."""

from gettext import NullTranslations
from typing import TypedDict

from aiogram.types import User
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.config import Settings
from bot.services.schemas import SettingsViewDTO


class WorkflowContext(TypedDict, total=False):
    """A dictionary to hold all data passed between middlewares and handlers.

    `total=False` is used because not all middlewares run for all events,
    so some keys may not be present in the data dictionary.
    Handlers and middlewares should still use `.get()` for safe access.
    The primary benefit is type hinting for keys that *are* present.
    """

    session: AsyncSession
    user_settings: SettingsViewDTO
    translator: NullTranslations

    event_from_user: User
    config: Settings
