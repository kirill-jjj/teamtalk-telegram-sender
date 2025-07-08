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
    recipients: list[int],
    event_user: TeamTalkUser,
    tt_instance: TeamTalkInstance,
    online_users_cache: dict[int, TeamTalkUser],
    services: "Services",
) -> list[int]:
    """Filters recipients based on Not on Online (NOON) logic."""
    final_recipients = []
    event_user_username = ttstr(event_user.username)

    for tg_user_id in recipients:
        user_settings = services.cache.get_user_settings(tg_user_id)

        if not is_user_subject_to_noon_check(user_settings):
            final_recipients.append(tg_user_id)
            continue

        # User has NOON enabled, now check if their linked TT user is online
        # This check was previously part of _should_send_silently but is more comprehensive here
        # when deciding *not* to send a notification.
        # _should_send_silently is about making a message silent if user is online.
        # This filtering is about *not sending at all* under certain NOON conditions.

        # If the event user is the bot itself, NOON logic for "only one user online" doesn't apply.
        if event_user.id == tt_instance.getMyUserID():
            final_recipients.append(tg_user_id)
            continue

        # Check if the event user is the configured admin_username (exempt from "only one online" rule for others)
        is_event_user_tt_admin = (
            services.config.general.admin_username and event_user_username == services.config.general.admin_username
        )

        if not is_event_user_tt_admin:
            # Check if the event_user is the *only* other user online (besides the bot itself)
            # in the instance where the event occurred.
            # If so, and the recipient has NOON enabled, they might not want a notification.
            other_users_online_in_instance_count = 0
            for online_user_id_in_instance in online_users_cache:
                if online_user_id_in_instance != tt_instance.getMyUserID():
                    other_users_online_in_instance_count += 1

            # If the event user is the only one online (excluding the bot)
            if other_users_online_in_instance_count == 1 and online_users_cache.get(event_user.id):
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
