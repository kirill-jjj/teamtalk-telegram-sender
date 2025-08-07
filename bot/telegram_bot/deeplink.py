"""Handles deeplink processing for Telegram bot commands like /start <token>."""

from gettext import NullTranslations
import logging

from aiogram.types import Message

from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.models import UserSettings
from bot.services.deeplink_service import DeeplinkService

logger = logging.getLogger(__name__)


async def handle_deeplink(
    message: Message,
    token: str,
    translator: NullTranslations,
    user_settings: UserSettings,
    deeplink_repo: DeeplinkRepository,
    deeplink_service: DeeplinkService,
) -> None:
    """Handles a /start command with a deeplink token.

    Validates the token, executes the associated action, and replies to the user.

    Args:
        message: The Aiogram Message object.
        token: The deeplink token from the command arguments.
        translator: The gettext translator object.
        user_settings: The UserSettings object for the user.
        deeplink_repo: The deeplink repository.
        deeplink_service: The deeplink service.
    """
    _ = translator.gettext
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        await message.reply(_("An error occurred. Please try again later."))
        return

    deeplink = await deeplink_repo.get_and_delete_if_expired(token)
    if not deeplink:
        await message.reply(_("Invalid or expired deeplink."))
        return

    if deeplink.expected_telegram_id and deeplink.expected_telegram_id != message.from_user.id:
        await message.reply(_("This confirmation link was intended for a different Telegram account."))
        return

    reply_text = await deeplink_service.execute_deeplink(deeplink, user_settings, translator)
    await message.reply(reply_text)

    # The token is now used, so we should delete it.
    await deeplink_repo.delete(deeplink)
