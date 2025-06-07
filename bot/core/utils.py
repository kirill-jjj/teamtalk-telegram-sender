import logging
from typing import Optional, Union

import pytalk # Required for TeamTalkInstance, TeamTalkUser, ttstr
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from pytalk.user_account import UserAccount as TeamTalkUserAccount

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

def get_username_as_str(user_or_account: Union[TeamTalkUser, TeamTalkUserAccount]) -> str:
    """Safely gets the username from a Pytalk User or UserAccount object as a string."""
    username_val = None
    if hasattr(user_or_account, 'username'): # Standard for pytalk.user.User
        username_val = user_or_account.username
    elif hasattr(user_or_account, '_account') and hasattr(user_or_account._account, 'szUsername'): # For pytalk.UserAccount
        # This case handles the structure seen in cq_toggle_specific_user_mute_action for UserAccount
        username_val = user_or_account._account.szUsername
    elif hasattr(user_or_account, 'szUsername'): # Direct access if szUsername is an attribute
         username_val = user_or_account.szUsername


    if isinstance(username_val, bytes):
        return ttstr(username_val)

    return str(username_val) if username_val is not None else ""

def build_help_message(language: str, platform: str, is_admin: bool) -> str:
    """Builds a contextual help message based on platform and user rights."""
    parts = []
    if platform == "telegram":
        parts.append(get_text("HELP_TELEGRAM_USER_HEADER", language))
        parts.append(get_text("HELP_TELEGRAM_USER_COMMANDS", language))
        if is_admin:
            parts.append(get_text("HELP_TELEGRAM_ADMIN_HEADER", language))
            parts.append(get_text("HELP_TELEGRAM_ADMIN_COMMANDS", language))
    elif platform == "teamtalk":
        parts.append(get_text("HELP_TEAMTALK_USER_HEADER", language))
        parts.append(get_text("HELP_TEAMTALK_USER_COMMANDS", language))
        if is_admin:
            parts.append(get_text("HELP_TEAMTALK_ADMIN_HEADER", language))
            parts.append(get_text("HELP_TEAMTALK_ADMIN_COMMANDS", language))

    return "\n".join(parts)
