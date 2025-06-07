import logging
from typing import Optional

import pytalk # Required for TeamTalkInstance, TeamTalkUser, ttstr
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.config import app_config
from bot.localization import get_text

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

def get_effective_server_name(tt_instance: Optional[TeamTalkInstance]) -> str:
    server_name = app_config.get("SERVER_NAME")
    if not server_name:
        if tt_instance and tt_instance.connected:
            try:
                server_name = ttstr(tt_instance.server.get_properties().server_name)
                if not server_name:  # Ensure empty string from ttstr is also treated as not found
                    server_name = "Unknown Server"
            except Exception as e:
                logger.error(f"Error getting server name from TT instance: {e}")
                server_name = "Unknown Server"
        else:
            server_name = "Unknown Server"
    return server_name if server_name else "Unknown Server" # Final fallback

def get_tt_user_display_name(user: TeamTalkUser, language_code: str) -> str:
    display_name = ttstr(user.nickname)
    if not display_name:
        display_name = ttstr(user.username)
    if not display_name:
        display_name = get_text("WHO_USER_UNKNOWN", language_code)
    return display_name

def pluralize(number: int, one: str, few: str, many: str) -> str:
    """
    Selects the correct plural form of a word based on the number,
    following Russian language rules.
    """
    num_mod100 = number % 100
    if 11 <= num_mod100 <= 19:
        return many

    num_mod10 = number % 10
    if num_mod10 == 1:
        return one
    if 2 <= num_mod10 <= 4:
        return few

    return many
