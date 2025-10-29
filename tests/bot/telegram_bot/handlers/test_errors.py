"""Tests for the global error handler."""

from collections.abc import Callable
from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock, call

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User
from aiogram.types.error_event import ErrorEvent
import pytest

from bot.config import Settings
from bot.telegram_bot.handlers.errors import universal_error_handler


@pytest.fixture
def mock_bot() -> MagicMock:
    """Fixture for a mocked bot."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def mock_settings() -> MagicMock:
    """Fixture for mocked settings."""
    settings = MagicMock(spec=Settings)
    settings.telegram = MagicMock()
    settings.telegram.admin_chat_id = 98765
    settings.general = MagicMock()
    settings.general.default_lang = "en"
    return settings


@pytest.fixture
def mock_translator_factory() -> MagicMock:
    """Fixture for a mocked translator factory."""
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda text: text  # Identity
    translator_factory = MagicMock(spec=Callable)
    translator_factory.return_value = translator
    return translator_factory


@pytest.fixture
def mock_subscription_service() -> MagicMock:
    """Fixture for a mocked subscription service."""
    service = MagicMock()
    service.delete_profile = AsyncMock()
    return service


@pytest.fixture
def mock_uow() -> MagicMock:
    """Fixture for a mocked Unit of Work."""
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=None)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    return uow


@pytest.fixture
def mock_cache() -> MagicMock:
    """Fixture for a mocked cache service."""
    return MagicMock()


async def run_handler(
    event: ErrorEvent,
    bot: MagicMock,
    settings: MagicMock,
    translator_factory: MagicMock,
    subscription_service: MagicMock,
    cache: MagicMock,
    uow: MagicMock,
) -> bool:
    """Helper to run the error handler with all mocks."""
    return await universal_error_handler(
        event,
        bot=bot,
        settings=settings,
        translator_factory=translator_factory,
        subscription_service=subscription_service,
        cache=cache,
        uow=uow,
    )


@pytest.mark.asyncio
async def test_general_error_with_message(
    mock_bot: MagicMock,
    mock_settings: MagicMock,
    mock_translator_factory: MagicMock,
    mock_subscription_service: MagicMock,
    mock_cache: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the handler for a generic error with a message update."""
    # Arrange
    chat_id = 12345
    exception = ValueError("Something went wrong")
    update = Update(
        update_id=1,
        message=Message(message_id=2, date=123, chat=Chat(id=chat_id, type="private")),
    )
    event = ErrorEvent(update=update, exception=exception)

    mock_bot.send_message.side_effect = [
        TelegramAPIError(method="sendMessage", message="User message failed"),
        AsyncMock(),
    ]

    # Act
    handled = await run_handler(
        event,
        mock_bot,
        mock_settings,
        mock_translator_factory,
        mock_subscription_service,
        mock_cache,
        mock_uow,
    )

    # Assert
    assert handled is True
    mock_bot.send_message.assert_has_awaits(
        [
            call(chat_id, text="An error occurred. Please try again later."),
            call(
                mock_settings.telegram.admin_chat_id,
                text=(
                    "Critical Error!\n\nType: ValueError\nError: Something went "
                    "wrong\n\nUpdate ID: 1\nChat ID: 12345"
                ),
                entities=[
                    MessageEntity(
                        type="bold",
                        offset=0,
                        length=15,
                        url=None,
                        user=None,
                        language=None,
                        custom_emoji_id=None,
                    ),
                    MessageEntity(
                        type="bold",
                        offset=17,
                        length=6,
                        url=None,
                        user=None,
                        language=None,
                        custom_emoji_id=None,
                    ),
                    MessageEntity(
                        type="bold",
                        offset=34,
                        length=7,
                        url=None,
                        user=None,
                        language=None,
                        custom_emoji_id=None,
                    ),
                    MessageEntity(
                        type="bold",
                        offset=63,
                        length=11,
                        url=None,
                        user=None,
                        language=None,
                        custom_emoji_id=None,
                    ),
                    MessageEntity(
                        type="bold",
                        offset=76,
                        length=9,
                        url=None,
                        user=None,
                        language=None,
                        custom_emoji_id=None,
                    ),
                ],
                parse_mode=None,
            ),
        ]
    )
    mock_subscription_service.delete_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_error_with_callback_query(
    mock_bot: MagicMock,
    mock_settings: MagicMock,
    mock_translator_factory: MagicMock,
    mock_subscription_service: MagicMock,
    mock_cache: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the handler for a generic error with a callback query update."""
    # Arrange
    chat_id = 12345
    exception = ValueError("Something went wrong with callback")
    update = MagicMock(spec=Update)
    update.update_id = 1
    update.update_id = 1
    update.callback_query = MagicMock(spec=CallbackQuery)
    update.callback_query.from_user = MagicMock(spec=User)
    update.callback_query.from_user.id = chat_id
    update.callback_query.answer = AsyncMock()
    update.model_dump.return_value = {"callback_query": {"from": {"id": chat_id}}}
    event = ErrorEvent(update=update, exception=exception)

    # Act
    handled = await run_handler(
        event,
        mock_bot,
        mock_settings,
        mock_translator_factory,
        mock_subscription_service,
        mock_cache,
        mock_uow,
    )

    # Assert
    assert handled is True
    update.callback_query.answer.assert_awaited_once_with(
        "An error occurred. Please try again later.", show_alert=True
    )
    mock_bot.send_message.assert_awaited_once_with(
        mock_settings.telegram.admin_chat_id,
        text=(
            "Critical Error!\n\nType: ValueError\nError: Something went wrong "
            "with callback\n\nUpdate ID: 1\nChat ID: 12345"
        ),
        entities=[
            MessageEntity(
                type="bold",
                offset=0,
                length=15,
                url=None,
                user=None,
                language=None,
                custom_emoji_id=None,
            ),
            MessageEntity(
                type="bold",
                offset=17,
                length=6,
                url=None,
                user=None,
                language=None,
                custom_emoji_id=None,
            ),
            MessageEntity(
                type="bold",
                offset=34,
                length=7,
                url=None,
                user=None,
                language=None,
                custom_emoji_id=None,
            ),
            MessageEntity(
                type="bold",
                offset=77,
                length=11,
                url=None,
                user=None,
                language=None,
                custom_emoji_id=None,
            ),
            MessageEntity(
                type="bold",
                offset=90,
                length=9,
                url=None,
                user=None,
                language=None,
                custom_emoji_id=None,
            ),
        ],
        parse_mode=None,
    )
    mock_subscription_service.delete_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_blocked_error(
    mock_bot: MagicMock,
    mock_settings: MagicMock,
    mock_translator_factory: MagicMock,
    mock_subscription_service: MagicMock,
    mock_cache: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the handler for a TelegramForbiddenError (bot blocked)."""
    # Arrange
    chat_id = 12345
    exception = TelegramForbiddenError(
        method="sendMessage", message="bot was blocked by the user"
    )
    update = Update(
        update_id=1,
        message=Message(message_id=2, date=123, chat=Chat(id=chat_id, type="private")),
    )
    event = ErrorEvent(update=update, exception=exception)

    # Act
    handled = await run_handler(
        event,
        mock_bot,
        mock_settings,
        mock_translator_factory,
        mock_subscription_service,
        mock_cache,
        mock_uow,
    )

    # Assert
    assert handled is True
    mock_subscription_service.delete_profile.assert_awaited_once()
    mock_uow.commit.assert_awaited_once()
    # Ensure no message is sent
    mock_bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_not_found_error(
    mock_bot: MagicMock,
    mock_settings: MagicMock,
    mock_translator_factory: MagicMock,
    mock_subscription_service: MagicMock,
    mock_cache: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the handler for a TelegramBadRequest (chat not found)."""
    # Arrange
    chat_id = 12345
    exception = TelegramBadRequest(method="sendMessage", message="chat not found")
    update = Update(
        update_id=1,
        message=Message(message_id=2, date=123, chat=Chat(id=chat_id, type="private")),
    )
    event = ErrorEvent(update=update, exception=exception)

    # Act
    handled = await run_handler(
        event,
        mock_bot,
        mock_settings,
        mock_translator_factory,
        mock_subscription_service,
        mock_cache,
        mock_uow,
    )

    # Assert
    assert handled is True
    mock_subscription_service.delete_profile.assert_awaited_once()
    mock_uow.commit.assert_awaited_once()
    # Ensure no message is sent
    mock_bot.send_message.assert_not_awaited()
