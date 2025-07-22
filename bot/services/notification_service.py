"""Service for advanced notification logic like NOON."""

import logging
from typing import TYPE_CHECKING

import pytalk  # Required for ttstr
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.models import UserSettings

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def is_user_subject_to_noon_check(user_settings: UserSettings | None) -> bool:
    """Checks if a user has NOON enabled and confirmed."""
    if not user_settings:
        return False
    return user_settings.not_on_online_enabled and user_settings.not_on_online_confirmed


async def is_linked_user_online(
    telegram_id: int,
    services: "Services",
    online_users_cache: dict[int, TeamTalkUser],
) -> bool:
    """Checks if the TeamTalk user linked to the given telegram_id is online."""
    user_settings = services.cache.get_user_settings(telegram_id)
    if not user_settings or not user_settings.teamtalk_username:
        return False

    linked_tt_username = user_settings.teamtalk_username
    return any(ttstr(tt_user_obj.username) == linked_tt_username for tt_user_obj in online_users_cache.values())


async def filter_recipients_for_noon(
    recipients_data: list[tuple[int, bool, bool]],
    event_user: TeamTalkUser,
    tt_instance: TeamTalkInstance,
    online_users_cache: dict[int, TeamTalkUser],
    services: "Services",
) -> list[int]:
    """Filters recipients based on Not on Online (NOON) logic using pre-fetched data."""
    final_recipients = []
    event_user_username = ttstr(event_user.username)

    for tg_user_id, noon_enabled, noon_confirmed in recipients_data:
        # The check is now done with the data passed directly, not from cache
        if not (noon_enabled and noon_confirmed):
            final_recipients.append(tg_user_id)
            continue

        # The rest of the NOON logic remains the same
        if event_user.id == tt_instance.getMyUserID():
            final_recipients.append(tg_user_id)
            continue

        is_event_user_tt_admin = (
            services.config.general.admin_username and event_user_username == services.config.general.admin_username
        )

        if not is_event_user_tt_admin:
            other_users_online_in_instance_count = sum(
                1 for user_id in online_users_cache if user_id != tt_instance.getMyUserID()
            )

            if other_users_online_in_instance_count == 1 and event_user.id in online_users_cache:
                logger.debug(
                    "NOON: Event user %s is the only one online (besides bot) for TG user %s "
                    "on server %s. Skipping notification for this recipient.",
                    event_user_username,
                    tg_user_id,
                    tt_instance.server_info.host,
                )
                continue

        final_recipients.append(tg_user_id)

    return final_recipients
