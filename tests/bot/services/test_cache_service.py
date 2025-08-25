import pytest

from bot.models import UserSettings
from bot.services.cache_service import CacheService


@pytest.fixture
def user_settings_cache_mock() -> dict[int, UserSettings]:
    return {}


@pytest.fixture
def admin_ids_cache_mock() -> set[int]:
    return set()


@pytest.fixture
def subscribed_users_cache_mock() -> set[int]:
    return set()


@pytest.fixture
def cache_service(
    user_settings_cache_mock: dict[int, UserSettings],
    admin_ids_cache_mock: set[int],
    subscribed_users_cache_mock: set[int],
) -> CacheService:
    return CacheService(
        user_settings_cache_mock, admin_ids_cache_mock, subscribed_users_cache_mock
    )


def test_cache_service_initialization(
    cache_service: CacheService,
    user_settings_cache_mock: dict[int, UserSettings],
    admin_ids_cache_mock: set[int],
    subscribed_users_cache_mock: set[int],
) -> None:
    assert cache_service._user_settings_cache == user_settings_cache_mock
    assert cache_service._admin_ids_cache == admin_ids_cache_mock
    assert cache_service._subscribed_users_cache == subscribed_users_cache_mock
    assert cache_service._bot_username is None


def test_set_bot_username(cache_service: CacheService) -> None:
    username = "test_bot"
    cache_service.set_bot_username(username)
    assert cache_service._bot_username == username


def test_get_bot_username(cache_service: CacheService) -> None:
    cache_service._bot_username = "another_bot"
    assert cache_service.get_bot_username() == "another_bot"


def test_get_bot_username_none(cache_service: CacheService) -> None:
    cache_service._bot_username = None
    assert cache_service.get_bot_username() is None


def test_add_admin(cache_service: CacheService) -> None:
    telegram_id = 123
    cache_service.add_admin(telegram_id)
    assert telegram_id in cache_service._admin_ids_cache


def test_remove_admin(cache_service: CacheService) -> None:
    telegram_id = 123
    cache_service._admin_ids_cache.add(telegram_id)
    cache_service.remove_admin(telegram_id)
    assert telegram_id not in cache_service._admin_ids_cache


def test_is_admin(cache_service: CacheService) -> None:
    telegram_id = 123
    cache_service._admin_ids_cache.add(telegram_id)
    assert cache_service.is_admin(telegram_id) is True
    assert cache_service.is_admin(456) is False


def test_load_admins_from_db(cache_service: CacheService) -> None:
    admin_ids = [1, 2, 3]
    cache_service._admin_ids_cache.add(99)  # Existing admin
    cache_service.load_admins_from_db(admin_ids)
    assert cache_service._admin_ids_cache == set(admin_ids)
    assert cache_service.get_admin_count() == len(admin_ids)


def test_get_all_admin_ids(cache_service: CacheService) -> None:
    admin_ids = {1, 2, 3}
    cache_service._admin_ids_cache = admin_ids
    retrieved_ids = cache_service.get_all_admin_ids()
    assert retrieved_ids == admin_ids
    assert retrieved_ids is not admin_ids  # Ensure a copy is returned


def test_get_admin_count(cache_service: CacheService) -> None:
    cache_service._admin_ids_cache = {1, 2, 3, 4}
    expected_count = 4
    assert cache_service.get_admin_count() == expected_count
    cache_service._admin_ids_cache.clear()
    assert cache_service.get_admin_count() == 0


def test_add_subscriber(cache_service: CacheService) -> None:
    telegram_id = 123
    cache_service.add_subscriber(telegram_id)
    assert telegram_id in cache_service._subscribed_users_cache


def test_remove_subscriber(cache_service: CacheService) -> None:
    telegram_id = 123
    cache_service._subscribed_users_cache.add(telegram_id)
    cache_service.remove_subscriber(telegram_id)
    assert telegram_id not in cache_service._subscribed_users_cache


def test_is_subscribed(cache_service: CacheService) -> None:
    telegram_id = 123
    cache_service._subscribed_users_cache.add(telegram_id)
    assert cache_service.is_subscribed(telegram_id) is True
    assert cache_service.is_subscribed(456) is False


def test_load_subscribers_from_db(cache_service: CacheService) -> None:
    subscriber_ids = [1, 2, 3]
    cache_service._subscribed_users_cache.add(99)  # Existing subscriber
    cache_service.load_subscribers_from_db(subscriber_ids)
    assert cache_service._subscribed_users_cache == set(subscriber_ids)


def test_get_all_subscriber_ids(cache_service: CacheService) -> None:
    subscriber_ids = {1, 2, 3}
    cache_service._subscribed_users_cache = subscriber_ids
    retrieved_ids = cache_service.get_all_subscriber_ids()
    assert retrieved_ids == subscriber_ids
    assert retrieved_ids is not subscriber_ids  # Ensure a copy is returned


def test_get_user_settings(cache_service: CacheService) -> None:
    telegram_id = 123
    settings = UserSettings(telegram_id=telegram_id, language_code="en")
    cache_service._user_settings_cache[telegram_id] = settings
    assert cache_service.get_user_settings(telegram_id) == settings
    assert cache_service.get_user_settings(456) is None


def test_update_user_settings(cache_service: CacheService) -> None:
    telegram_id = 123
    settings = UserSettings(telegram_id=telegram_id, language_code="en")
    cache_service.update_user_settings(settings)
    assert cache_service._user_settings_cache[telegram_id] == settings


def test_update_user_settings_invalid_type(cache_service: CacheService) -> None:
    # Attempt to update with a non-UserSettings object
    cache_service.update_user_settings("invalid_settings")
    assert len(cache_service._user_settings_cache) == 0


def test_remove_user_settings(cache_service: CacheService) -> None:
    telegram_id = 123
    settings = UserSettings(telegram_id=telegram_id, language_code="en")
    cache_service._user_settings_cache[telegram_id] = settings
    cache_service.remove_user_settings(telegram_id)
    assert telegram_id not in cache_service._user_settings_cache


def test_remove_user_settings_not_in_cache(cache_service: CacheService) -> None:
    # Should not raise an error if user settings not in cache
    cache_service.remove_user_settings(456)
    assert len(cache_service._user_settings_cache) == 0


def test_load_all_user_settings(cache_service: CacheService) -> None:
    settings_list = [
        UserSettings(telegram_id=1, language_code="en"),
        UserSettings(telegram_id=2, language_code="ru"),
    ]
    cache_service._user_settings_cache[99] = UserSettings(
        telegram_id=99, language_code="uk"
    )  # Existing
    cache_service.load_all_user_settings(settings_list)
    expected_len = 2
    assert len(cache_service._user_settings_cache) == expected_len
    assert cache_service._user_settings_cache[1] == settings_list[0]
    assert cache_service._user_settings_cache[2] == settings_list[1]


def test_load_all_user_settings_with_invalid_type(cache_service: CacheService) -> None:
    settings_list = [
        UserSettings(telegram_id=1, language_code="en"),
        "invalid_settings",  # Invalid type
        UserSettings(telegram_id=2, language_code="ru"),
    ]
    cache_service.load_all_user_settings(settings_list)
    expected_len = 2
    assert len(cache_service._user_settings_cache) == expected_len
    assert cache_service._user_settings_cache[1] == settings_list[0]
    assert cache_service._user_settings_cache[2] == settings_list[2]


def test_remove_user_profile(cache_service: CacheService) -> None:
    telegram_id = 123
    # Populate caches
    cache_service._admin_ids_cache.add(telegram_id)
    cache_service._subscribed_users_cache.add(telegram_id)
    cache_service._user_settings_cache[telegram_id] = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )

    cache_service.remove_user_profile(telegram_id)

    assert telegram_id not in cache_service._admin_ids_cache
    assert telegram_id not in cache_service._subscribed_users_cache
    assert telegram_id not in cache_service._user_settings_cache
