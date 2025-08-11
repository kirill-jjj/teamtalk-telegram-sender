"""Shared utility functions for creating keyboards."""

from bot.core.enums import NotificationSetting
from bot.core.languages import LanguageInfo


def get_notification_settings_options() -> list[tuple[str, str]]:
    """Returns the list of options for notification settings."""
    settings_map_source = {
        NotificationSetting.ALL: ("All (Join & Leave)", NotificationSetting.ALL.value),
        NotificationSetting.LEAVE_OFF: (
            "Join Only",
            NotificationSetting.LEAVE_OFF.value,
        ),
        NotificationSetting.JOIN_OFF: (
            "Leave Only",
            NotificationSetting.JOIN_OFF.value,
        ),
        NotificationSetting.NONE: ("None", NotificationSetting.NONE.value),
    }
    return [
        (val_str, text_source)
        for _setting_enum, (text_source, val_str) in settings_map_source.items()
    ]


def get_language_options(
    available_languages: list[LanguageInfo],
) -> list[tuple[str, str]]:
    """Returns the list of options for language selection."""
    return [(lang["code"], lang["native_name"]) for lang in available_languages]
