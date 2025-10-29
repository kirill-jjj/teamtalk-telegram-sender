from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from bot.database.models import UserSettings
from bot.database.types import MuteListMode, NotificationSetting
from bot.database.uow import IUnitOfWork
from bot.services.user_settings_service import UserSettingsService


@pytest.fixture
def mock_uow() -> AsyncMock:
    uow = AsyncMock(spec=IUnitOfWork)
    uow.users = AsyncMock()
    return uow


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.get_user_settings = MagicMock()
    cache.update_user_settings = MagicMock()
    return cache


@pytest.fixture
def user_settings_service(
    mock_uow: AsyncMock, mock_cache: MagicMock
) -> UserSettingsService:
    return UserSettingsService(mock_uow, mock_cache)


@pytest.mark.asyncio
async def test_get_or_create_from_cache(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    default_lang = "en"
    cached_settings = UserSettings(telegram_id=telegram_id, language_code=default_lang)
    mock_cache.get_user_settings.return_value = cached_settings

    result = await user_settings_service.get_or_create(
        mock_uow, telegram_id, default_lang
    )

    assert result == cached_settings
    mock_cache.get_user_settings.assert_called_once_with(telegram_id)
    mock_uow.users.get_or_create.assert_not_called()
    mock_uow.commit.assert_not_called()
    mock_cache.update_user_settings.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_from_db(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    default_lang = "en"
    db_settings = UserSettings(telegram_id=telegram_id, language_code=default_lang)

    mock_cache.get_user_settings.return_value = None
    mock_uow.users.get_or_create.return_value = db_settings

    result = await user_settings_service.get_or_create(
        mock_uow, telegram_id, default_lang
    )

    assert result == db_settings
    mock_cache.get_user_settings.assert_called_once_with(telegram_id)
    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id, defaults={"language_code": default_lang}
    )
    mock_cache.update_user_settings.assert_called_once_with(db_settings)


@pytest.mark.asyncio
async def test_update_language_success(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    new_lang_code = "ru"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.users.get_by_id.return_value = user_settings

    result = await user_settings_service.update_language(
        mock_uow, telegram_id, new_lang_code
    )

    assert result.language_code == new_lang_code
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)
    mock_uow.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_update_language_no_change(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    new_lang_code = "en"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    mock_uow.users.get_by_id.return_value = user_settings

    result = await user_settings_service.update_language(
        mock_uow, telegram_id, new_lang_code
    )

    assert result is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_not_called()
    mock_cache.update_user_settings.assert_not_called()
    mock_uow.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_update_language_user_not_found(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    new_lang_code = "ru"

    mock_uow.users.get_by_id.return_value = None

    result = await user_settings_service.update_language(
        mock_uow, telegram_id, new_lang_code
    )

    assert result is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_not_called()
    mock_cache.update_user_settings.assert_not_called()
    mock_uow.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_update_language_sqlalchemy_error(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    new_lang_code = "ru"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.users.get_by_id.return_value = user_settings
    mock_uow.users.save.side_effect = SQLAlchemyError("DB Error")

    result = await user_settings_service.update_language(
        mock_uow, telegram_id, new_lang_code
    )

    assert result is None
    assert user_settings.language_code == "en"
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_not_called()
    mock_uow.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_update_mute_mode_success(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    new_mode = MuteListMode.whitelist
    user_settings = UserSettings(
        telegram_id=telegram_id,
        language_code="en",
        mute_list_mode=MuteListMode.blacklist,
    )

    mock_uow.users.get_by_id.return_value = user_settings

    result = await user_settings_service.update_mute_mode(
        mock_uow, telegram_id, new_mode
    )

    assert result.mute_list_mode == new_mode
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)
    mock_uow.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_update_mute_mode_user_not_found(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
) -> None:
    telegram_id = 123
    new_mode = MuteListMode.whitelist

    mock_uow.users.get_by_id.return_value = None

    result = await user_settings_service.update_mute_mode(
        mock_uow, telegram_id, new_mode
    )

    assert result is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_not_called()


@pytest.mark.asyncio
async def test_update_notification_preference_success(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    new_pref = NotificationSetting.JOIN_OFF
    user_settings = UserSettings(
        telegram_id=telegram_id,
        language_code="en",
        notification_settings=NotificationSetting.ALL,
    )

    mock_uow.users.get_by_id.return_value = user_settings

    result = await user_settings_service.update_notification_preference(
        mock_uow, telegram_id, new_pref
    )

    assert result.notification_settings == new_pref
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)
    mock_uow.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_update_notification_preference_user_not_found(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
) -> None:
    telegram_id = 123
    new_pref = NotificationSetting.JOIN_OFF

    mock_uow.users.get_by_id.return_value = None

    result = await user_settings_service.update_notification_preference(
        mock_uow, telegram_id, new_pref
    )

    assert result is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_not_called()


@pytest.mark.asyncio
async def test_toggle_noon_setting_enable(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    user_settings = UserSettings(
        telegram_id=123,
        language_code="en",
        not_on_online_enabled=False,
        not_on_online_confirmed=False,
    )
    mock_uow.users.get_by_id.return_value = user_settings

    result = await user_settings_service.toggle_noon_setting(
        mock_uow, user_settings.telegram_id
    )

    assert result.not_on_online_enabled is True
    assert result.not_on_online_confirmed is True
    expected_calls = 2
    assert mock_uow.users.save.call_count == expected_calls
    assert mock_cache.update_user_settings.call_count == expected_calls


@pytest.mark.asyncio
async def test_toggle_noon_setting_disable(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    user_settings = UserSettings(
        telegram_id=123,
        language_code="en",
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
    )
    mock_uow.users.get_by_id.return_value = user_settings

    result = await user_settings_service.toggle_noon_setting(
        mock_uow, user_settings.telegram_id
    )

    assert result.not_on_online_enabled is False
    assert result.not_on_online_confirmed is True
    expected_calls = 1
    assert mock_uow.users.save.call_count == expected_calls
    assert mock_cache.update_user_settings.call_count == expected_calls


@pytest.mark.asyncio
async def test_toggle_noon_setting_user_not_found(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.users.get_by_id.return_value = None

    result = await user_settings_service.toggle_noon_setting(mock_uow, telegram_id)

    assert result is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_not_called()


@pytest.mark.asyncio
async def test_toggle_noon_setting_update_fails(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    user_settings = UserSettings(
        telegram_id=123,
        language_code="en",
        not_on_online_enabled=False,
        not_on_online_confirmed=False,
    )
    mock_uow.users.get_by_id.return_value = user_settings
    mock_uow.users.save.side_effect = SQLAlchemyError("DB Error")

    result = await user_settings_service.toggle_noon_setting(
        mock_uow, user_settings.telegram_id
    )

    assert result is None
    mock_uow.users.get_by_id.assert_called_once_with(user_settings.telegram_id)
    assert mock_uow.users.save.call_count == 1
    mock_cache.update_user_settings.assert_not_called()


@pytest.mark.asyncio
async def test_unlink_tt_account_success(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    user_settings = UserSettings(
        telegram_id=123, language_code="en", teamtalk_username="linked_tt_user"
    )
    mock_uow.users.get_by_id.return_value = user_settings

    result_settings, result_username = await user_settings_service.unlink_tt_account(
        mock_uow, user_settings.telegram_id
    )

    assert result_settings.teamtalk_username is None
    assert result_username == "linked_tt_user"
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_unlink_tt_account_no_account_linked(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    user_settings = UserSettings(
        telegram_id=123, language_code="en", teamtalk_username=None
    )
    mock_uow.users.get_by_id.return_value = user_settings

    result_settings, result_username = await user_settings_service.unlink_tt_account(
        mock_uow, user_settings.telegram_id
    )

    assert result_settings is not None
    assert result_username is None
    mock_uow.users.save.assert_not_called()
    mock_cache.update_user_settings.assert_not_called()


@pytest.mark.asyncio
async def test_unlink_tt_account_user_not_found(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.users.get_by_id.return_value = None

    result_settings, result_username = await user_settings_service.unlink_tt_account(
        mock_uow, telegram_id
    )

    assert result_settings is None
    assert result_username is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.save.assert_not_called()


@pytest.mark.asyncio
async def test_get_user_settings_view(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    default_lang = "en"
    user_settings = UserSettings(
        telegram_id=telegram_id,
        language_code=default_lang,
        notification_settings=NotificationSetting.ALL,
        mute_list_mode=MuteListMode.blacklist,
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="test_user",
        muted_users_list=[],
    )
    mock_cache.get_user_settings.return_value = None
    mock_uow.users.get_or_create.return_value = user_settings

    result = await user_settings_service.get_user_settings_view(
        mock_uow, telegram_id, default_lang
    )

    assert result.language_code == default_lang
    assert result.notification_settings == NotificationSetting.ALL
    assert result.mute_list_mode == MuteListMode.blacklist
    assert result.not_on_online_enabled is True
    assert result.teamtalk_username == "test_user"
    assert result.muted_users_count == 0


@pytest.mark.asyncio
async def test_get_subscriber_view_data(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telegram_id = 123
    default_lang = "en"
    user_settings = UserSettings(telegram_id=telegram_id, language_code=default_lang)
    mock_cache.get_user_settings.return_value = user_settings
    mock_bot = AsyncMock()
    monkeypatch.setattr(
        "bot.services.user_settings_service.get_display_name_for_id",
        AsyncMock(return_value="John Doe"),
    )

    result = await user_settings_service.get_subscriber_view_data(
        mock_uow, telegram_id, default_lang, mock_bot
    )

    assert result is not None
    assert result.user_settings == user_settings
    assert result.display_name == "John Doe"


@pytest.mark.asyncio
async def test_get_subscriber_view_data_user_settings_none(
    user_settings_service: UserSettingsService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telegram_id = 123
    default_lang = "en"
    mock_cache.get_user_settings.return_value = None
    mock_uow.users.get_or_create.return_value = None
    mock_bot = AsyncMock()
    mock_get_display_name = AsyncMock(return_value="John Doe")
    monkeypatch.setattr(
        "bot.services.user_settings_service.get_display_name_for_id",
        mock_get_display_name,
    )

    result = await user_settings_service.get_subscriber_view_data(
        mock_uow, telegram_id, default_lang, mock_bot
    )

    assert result is None
    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id, defaults={"language_code": default_lang}
    )
    mock_get_display_name.assert_not_called()


@pytest.mark.asyncio
async def test_get_account_management_data(
    mock_uow: AsyncMock,
) -> None:
    telegram_id = 123
    user_settings = UserSettings(telegram_id=telegram_id, teamtalk_username="test_user")
    mock_uow.users.get_by_id.return_value = user_settings

    result = await UserSettingsService.get_account_management_data(
        mock_uow, telegram_id
    )

    assert result.current_tt_username == "test_user"


@pytest.mark.asyncio
async def test_get_account_management_data_user_settings_none(
    mock_uow: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.users.get_by_id.return_value = None

    result = await UserSettingsService.get_account_management_data(
        mock_uow, telegram_id
    )

    assert result.current_tt_username is None
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
