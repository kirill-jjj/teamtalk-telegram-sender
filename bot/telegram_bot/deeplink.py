"""Handles deeplink processing for Telegram bot commands like /start <token>."""

import gettext
import logging
from typing import TYPE_CHECKING

from aiogram.types import Message
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.crud import (
    delete_deeplink_by_token,
)
from bot.database.crud import get_deeplink as db_get_deeplink
from bot.models import Deeplink as DeeplinkModel
from bot.models import UserSettings
from bot.services import deeplink_service

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


async def _validate_deeplink_token(
    session: AsyncSession, token: str, message_from_user_id: int, message: Message, translator: gettext.GNUTranslations
) -> DeeplinkModel | None:
    """Validates the deeplink token and checks if it's intended for the current user.

    Sends a reply and returns None if validation fails.
    """
    _ = translator.gettext
    deeplink_obj = await db_get_deeplink(session, token)
    if not deeplink_obj:
        await message.reply(_("Invalid or expired deeplink."))
        return None

    if deeplink_obj.expected_telegram_id and deeplink_obj.expected_telegram_id != message_from_user_id:
        await message.reply(_("This confirmation link was intended for a different Telegram account."))
        return None

    return deeplink_obj


async def _execute_deeplink(
    session: AsyncSession,
    telegram_id: int,
    translator: gettext.GNUTranslations,
    deeplink_obj: DeeplinkModel,
    user_settings: UserSettings,
    services: "Services",
) -> str:
    """Wrapper to call the deeplink_service.execute_deeplink."""
    return await deeplink_service.execute_deeplink(
        deeplink_obj=deeplink_obj,
        session=session,
        telegram_id=telegram_id,
        translator=translator,
        user_settings=user_settings,
        services=services,
    )


async def handle_deeplink(
    message: Message,
    token: str,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    services: "Services",
) -> None:
    """Handles a /start command with a deeplink token.

    Validates the token, executes the associated action, and replies to the user.

    Args:
        message: The Aiogram Message object.
        token: The deeplink token from the command arguments.
        session: The active AsyncSession.
        translator: The gettext translator object.
        user_settings: The UserSettings object for the user.
        services: The application's services container.
    """
    _ = translator.gettext
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        await message.reply(_("An error occurred. Please try again later."))
        return

    message_from_user_id = message.from_user.id

    deeplink_obj: DeeplinkModel | None = await _validate_deeplink_token(
        session, token, message_from_user_id, message, translator
    )
    if not deeplink_obj:
        return

    reply_text = await _execute_deeplink(
        session=session,
        telegram_id=message_from_user_id,
        translator=translator,
        deeplink_obj=deeplink_obj,
        user_settings=user_settings,
        services=services,
    )

    await message.reply(reply_text)
    await delete_deeplink_by_token(session, token)
