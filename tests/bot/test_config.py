from pathlib import Path

from pydantic import ValidationError
import pytest

from bot.config import (
    OperationalParameters,
    Settings,
)


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    """Creates a temporary valid config.toml file for testing."""
    config_content = """
    [general]
    default_lang = "en"
    gender = "neutral"
    admin_username = "test_admin"

    [database]
    db_file = "test_bot_data.db"

    [telegram]
    event_token = "test_event_token"
    message_token = "test_message_token"
    admin_chat_id = 12345

    [teamtalk]
    host_name = "test.teamtalk.com"
    port = 10333
    encrypted = true
    user_name = "TestBot"
    password = "TestPassword"
    channel = "/Test/Channel"
    channel_password = "ChannelPassword"
    nick_name = "TestNotifier"
    status_text = "Testing notifications"
    client_name = "TestClient"
    server_name = "TestServerName"
    global_ignore_usernames = ["IgnoredUser1", "IgnoredUser2"]

    [operational_parameters]
    deeplink_ttl_seconds = 600
    tt_reconnect_retry_seconds = 30
    tt_reconnect_check_interval_seconds = 20
    online_users_cache_sync_interval_seconds = 600
    user_settings_cache_max_size = 2000
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def invalid_toml_file(tmp_path: Path) -> Path:
    """Creates a temporary invalid TOML file for testing."""
    invalid_content = """
    [general
    default_lang = "en"
    """
    config_path = tmp_path / "invalid_config.toml"
    config_path.write_text(invalid_content)
    return config_path


@pytest.fixture
def missing_required_field_file(tmp_path: Path) -> Path:
    """Creates a temporary TOML file with a missing required field."""
    config_content = """
    [general]
    default_lang = "en"
    gender = "neutral"

    [database]
    db_file = "test_bot_data.db"

    [telegram]
    event_token = "test_event_token"
    # message_token is missing
    admin_chat_id = 12345

    [teamtalk]
    host_name = "test.teamtalk.com"
    port = 10333
    encrypted = false
    user_name = "TestBot"
    password = "TestPassword"
    channel = "/Test/Channel"
    nick_name = "TestNotifier"
    status_text = "Testing notifications"
    client_name = "TestClient"
    """
    config_path = tmp_path / "missing_field_config.toml"
    config_path.write_text(config_content)
    return config_path


def test_settings_from_toml_success(temp_config_file: Path) -> None:
    """Test loading settings from a valid TOML file."""
    settings = Settings.from_toml(str(temp_config_file))

    assert settings.general.default_lang == "en"
    assert settings.general.gender == "neutral"
    assert settings.general.admin_username == "test_admin"

    assert settings.database.db_file == "test_bot_data.db"

    assert settings.telegram.event_token == "test_event_token"
    assert settings.telegram.message_token == "test_message_token"
    assert settings.telegram.admin_chat_id == 12345

    assert settings.teamtalk.host_name == "test.teamtalk.com"
    assert settings.teamtalk.port == 10333
    assert settings.teamtalk.encrypted is True
    assert settings.teamtalk.user_name == "TestBot"
    assert settings.teamtalk.password == "TestPassword"
    assert settings.teamtalk.channel == "/Test/Channel"
    assert settings.teamtalk.channel_password == "ChannelPassword"
    assert settings.teamtalk.nick_name == "TestNotifier"
    assert settings.teamtalk.status_text == "Testing notifications"
    assert settings.teamtalk.client_name == "TestClient"
    assert settings.teamtalk.server_name == "TestServerName"
    assert settings.teamtalk.global_ignore_usernames == ["IgnoredUser1", "IgnoredUser2"]

    assert settings.operational_parameters.deeplink_ttl_seconds == 600
    assert settings.operational_parameters.tt_reconnect_retry_seconds == 30
    assert settings.operational_parameters.tt_reconnect_check_interval_seconds == 20
    assert (
        settings.operational_parameters.online_users_cache_sync_interval_seconds == 600
    )
    assert settings.operational_parameters.user_settings_cache_max_size == 2000

    assert settings._config_dir == temp_config_file.parent.resolve()


def test_settings_from_toml_file_not_found() -> None:
    """Test loading settings from a non-existent file."""
    with pytest.raises(FileNotFoundError, match="Config not found"):
        Settings.from_toml("non_existent_config.toml")


def test_settings_from_toml_invalid_toml(invalid_toml_file: Path) -> None:
    """Test loading settings from an invalid TOML file."""
    with pytest.raises(ValueError, match="TOML decode error"):
        Settings.from_toml(str(invalid_toml_file))


def test_settings_from_toml_missing_required_field(
    missing_required_field_file: Path,
) -> None:
    """Test loading settings from a TOML file with a missing required field."""
    with pytest.raises(ValidationError):
        Settings.from_toml(str(missing_required_field_file))


def test_settings_from_toml_default_operational_parameters(
    tmp_path: Path,
) -> None:
    """Test loading settings when operational_parameters are not specified,
    expecting defaults."""
    config_content = """
    [general]
    default_lang = "en"
    gender = "neutral"

    [database]
    db_file = "test_bot_data.db"

    [telegram]
    event_token = "test_event_token"
    message_token = "test_message_token"
    admin_chat_id = 12345

    [teamtalk]
    host_name = "test.teamtalk.com"
    port = 10333
    encrypted = false
    user_name = "TestBot"
    password = "TestPassword"
    channel = "/Test/Channel"
    nick_name = "TestNotifier"
    status_text = "Testing notifications"
    client_name = "TestClient"
    """
    config_path = tmp_path / "config_with_default_ops.toml"
    config_path.write_text(config_content)

    settings = Settings.from_toml(str(config_path))

    # Assert that default values are used for operational_parameters
    default_ops = OperationalParameters()
    assert (
        settings.operational_parameters.deeplink_ttl_seconds
        == default_ops.deeplink_ttl_seconds
    )
    assert (
        settings.operational_parameters.tt_reconnect_retry_seconds
        == default_ops.tt_reconnect_retry_seconds
    )
    assert (
        settings.operational_parameters.tt_reconnect_check_interval_seconds
        == default_ops.tt_reconnect_check_interval_seconds
    )
    assert (
        settings.operational_parameters.online_users_cache_sync_interval_seconds
        == default_ops.online_users_cache_sync_interval_seconds
    )
    assert (
        settings.operational_parameters.user_settings_cache_max_size
        == default_ops.user_settings_cache_max_size
    )
