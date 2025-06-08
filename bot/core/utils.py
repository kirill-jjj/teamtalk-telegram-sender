import logging
from typing import Optional, Union

import pytalk # Required for TeamTalkInstance, TeamTalkUser, ttstr
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from pytalk.user_account import UserAccount as TeamTalkUserAccount

from bot.config import app_config
# from bot.localization import get_text # Removed by this change

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

def get_tt_user_display_name(user: TeamTalkUser, _: callable) -> str:
    display_name = ttstr(user.nickname)
    if not display_name:
        display_name = ttstr(user.username)
    if not display_name:
        display_name = _("unknown user") # Was WHO_USER_UNKNOWN
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

def build_help_message(_: callable, platform: str, is_admin: bool, is_bot_admin: bool) -> str: # Added is_bot_admin
    """Builds a contextual help message based on platform and user rights."""
    parts = []
    if platform == "telegram":
        parts.append(_("<b>Available Commands:</b>")) # Changed to HTML bold
        parts.append(_("/who - Show online users.\n"
                       "/settings - Access the interactive settings menu (language, notifications, mute lists, NOON feature).\n"
                       "/help - Show this help message.\n"
                       "(Note: `/start` is used to initiate the bot and process deeplinks.)"))
        if is_admin: # This is_admin likely refers to general admin privileges on Telegram side
            parts.append(_("\n<b>Admin Commands:</b>")) # Changed to HTML bold
            parts.append(_("/kick - Kick a user from the server (via buttons).\n"
                           "/ban - Ban a user from the server (via buttons)."))
    elif platform == "teamtalk":
        parts.append(_("Available commands:")) # Keep as plain text for TeamTalk
        parts.append(_("/sub - Get a link to subscribe to notifications and link your TeamTalk account for NOON.\n"
                       "/unsub - Get a link to unsubscribe from notifications.\n"
                       "/help - Show help."))
        # For TeamTalk, is_admin might mean TT server admin, and is_bot_admin for specific bot management commands
        if is_bot_admin: # Assuming MAIN_ADMIN check maps to is_bot_admin
            parts.append(_("\nAdmin commands (MAIN_ADMIN from config only):")) # Keep as plain text
            parts.append(_("/add_admin <Telegram ID> [<Telegram ID>...] - Add bot admin.\n"
                           "/remove_admin <Telegram ID> [<Telegram ID>...] - Remove bot admin."))

    return "\n".join(parts)
