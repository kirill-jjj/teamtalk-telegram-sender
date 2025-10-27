import pytest

from bot.database.models import UserSettings
from bot.database.types import MuteListMode, NotificationSetting
from bot.services.schemas import (
    AccountManagementData,
    AdminManagementResult,
    AllAccountsViewData,
    BatchOperationResult,
    ModerationViewData,
    MuteListViewData,
    OperationResult,
    PaginatedResult,
    SettingsViewDTO,
    SubscriberInfo,
    SubscriberView,
    UserAccountInfo,
    UserDTO,
)


def test_settings_view_dto_valid_data() -> None:
    """Test SettingsViewDTO with valid data."""
    dto = SettingsViewDTO(
        telegram_id=123,
        language_code="en",
        notification_settings=NotificationSetting.ALL,
        mute_list_mode=MuteListMode.blacklist,
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="test_user",
        muted_users_count=5,
    )
    assert dto.language_code == "en"
    assert dto.notification_settings == NotificationSetting.ALL
    assert dto.mute_list_mode == MuteListMode.blacklist
    assert dto.not_on_online_enabled is True
    assert dto.teamtalk_username == "test_user"
    assert dto.muted_users_count == 5


def test_settings_view_dto_optional_fields() -> None:
    """Test SettingsViewDTO with optional fields as None."""
    dto = SettingsViewDTO(
        telegram_id=456,
        language_code="ru",
        notification_settings=NotificationSetting.NONE,
        mute_list_mode=MuteListMode.whitelist,
        not_on_online_enabled=False,
        not_on_online_confirmed=False,
        teamtalk_username=None,
        muted_users_count=0,
    )
    assert dto.teamtalk_username is None
    assert dto.muted_users_count == 0


@pytest.mark.parametrize(
    ("data", "expected_id", "expected_nickname", "expected_channel"),
    [
        (
            {"id": 1, "nickname": "User1", "channel_name": "General"},
            1,
            "User1",
            "General",
        ),
        ({"id": 2, "nickname": "Bot", "channel_name": "Lobby"}, 2, "Bot", "Lobby"),
    ],
)
def test_user_dto_valid_data(
    data: dict, expected_id: int, expected_nickname: str, expected_channel: str
) -> None:
    """Test UserDTO with valid data."""
    dto = UserDTO(**data)
    assert dto.id == expected_id
    assert dto.nickname == expected_nickname
    assert dto.channel_name == expected_channel


def test_user_account_info_valid_data() -> None:
    """Test UserAccountInfo with valid data."""
    dto = UserAccountInfo(username="account_name")
    assert dto.username == "account_name"


def test_subscriber_info_valid_data() -> None:
    """Test SubscriberInfo with valid data."""
    dto = SubscriberInfo(
        telegram_id=123, display_name="Test User", teamtalk_username="tt_user"
    )
    assert dto.telegram_id == 123
    assert dto.display_name == "Test User"
    assert dto.teamtalk_username == "tt_user"


def test_subscriber_info_optional_fields() -> None:
    """Test SubscriberInfo with optional fields as None."""
    dto = SubscriberInfo(
        telegram_id=456, display_name="Another User", teamtalk_username=None
    )
    assert dto.teamtalk_username is None


@pytest.mark.parametrize(
    ("items", "total_items", "total_pages", "current_page"),
    [
        ([1, 2], 10, 5, 0),
        ([], 0, 1, 0),
        (["a", "b", "c"], 3, 1, 0),
    ],
)
def test_paginated_result_valid_data(
    items: list, total_items: int, total_pages: int, current_page: int
) -> None:
    """Test PaginatedResult with valid data."""
    dto = PaginatedResult(
        items=items,
        total_items=total_items,
        total_pages=total_pages,
        current_page=current_page,
    )
    assert dto.items == items
    assert dto.total_items == total_items
    assert dto.total_pages == total_pages
    assert dto.current_page == current_page


def test_operation_result_valid_data() -> None:
    """Test OperationResult with valid data."""
    user_settings = UserSettings(telegram_id=1, language_code="en")
    dto = OperationResult(
        success=True,
        message_key="success_message",
        message_args={"key": "value"},
        user_settings=user_settings,
        long_message="Detailed success message",
    )
    assert dto.success is True
    assert dto.message_key == "success_message"
    assert dto.message_args == {"key": "value"}
    assert dto.user_settings == user_settings
    assert dto.long_message == "Detailed success message"


def test_operation_result_optional_fields() -> None:
    """Test OperationResult with optional fields as None."""
    dto = OperationResult(success=False, message_key="error_message")
    assert dto.message_args is None
    assert dto.user_settings is None
    assert dto.long_message is None


def test_batch_operation_result_valid_data() -> None:
    """Test BatchOperationResult with valid data."""
    dto = BatchOperationResult(successful_ids=[1, 2], failed_ids=[3])
    assert dto.successful_ids == [1, 2]
    assert dto.failed_ids == [3]


def test_batch_operation_result_default_values() -> None:
    """Test BatchOperationResult with default empty lists."""
    dto = BatchOperationResult()
    assert dto.successful_ids == []
    assert dto.failed_ids == []


def test_admin_management_result_valid_data() -> None:
    """Test AdminManagementResult with valid data."""
    add_result = BatchOperationResult(successful_ids=[1])
    remove_result = BatchOperationResult(failed_ids=[2])
    dto = AdminManagementResult(
        add_result=add_result,
        remove_result=remove_result,
        error_messages=["Error 1"],
    )
    assert dto.add_result == add_result
    assert dto.remove_result == remove_result
    assert dto.error_messages == ["Error 1"]


def test_mute_list_view_data_valid_data() -> None:
    """Test MuteListViewData with valid data."""
    dto = MuteListViewData(
        items=["user1", "user2"],
        title="Muted Users",
        empty_list_text="No muted users",
    )
    assert dto.items == ["user1", "user2"]
    assert dto.title == "Muted Users"
    assert dto.empty_list_text == "No muted users"


def test_all_accounts_view_data_valid_data() -> None:
    """Test AllAccountsViewData with valid data."""
    accounts = [UserAccountInfo(username="acc1"), UserAccountInfo(username="acc2")]
    dto = AllAccountsViewData(
        accounts=accounts,
        title="All Accounts",
        empty_list_text="No accounts",
    )
    assert dto.accounts == accounts
    assert dto.title == "All Accounts"
    assert dto.empty_list_text == "No accounts"


def test_account_management_data_valid_data() -> None:
    """Test AccountManagementData with valid data."""
    dto = AccountManagementData(current_tt_username="linked_tt")
    assert dto.current_tt_username == "linked_tt"


def test_account_management_data_optional_fields() -> None:
    """Test AccountManagementData with optional fields as None."""
    dto = AccountManagementData(current_tt_username=None)
    assert dto.current_tt_username is None


def test_subscriber_view_valid_data() -> None:
    """Test SubscriberView with valid data."""
    user_settings = UserSettings(telegram_id=1, language_code="en")
    dto = SubscriberView(user_settings=user_settings, display_name="Test User")
    assert dto.user_settings == user_settings
    assert dto.display_name == "Test User"


def test_moderation_view_data_valid_data() -> None:
    """Test ModerationViewData with valid data."""
    users = [UserDTO(id=1, nickname="User1", channel_name="Channel1")]
    dto = ModerationViewData(
        users=users,
        server_name="Test Server",
        error_message="Something went wrong",
    )
    assert dto.users == users
    assert dto.server_name == "Test Server"
    assert dto.error_message == "Something went wrong"


def test_moderation_view_data_optional_fields() -> None:
    """Test ModerationViewData with optional fields as None."""
    users = [UserDTO(id=1, nickname="User1", channel_name="Channel1")]
    dto = ModerationViewData(users=users, server_name="Test Server", error_message=None)
    assert dto.error_message is None
