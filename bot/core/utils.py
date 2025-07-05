import gettext
import logging
from typing import Optional, Union, List, Any # Added Any
from pytalk.implementation.TeamTalkPy import TeamTalk5 # Keep for type hint if specific

import pytalk
from pytalk.instance import TeamTalkInstance # Keep for type hint
from pytalk.user import User as TeamTalkUser
from pytalk.user_account import UserAccount as TeamTalkUserAccount

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

def get_effective_server_name(tt_instance: Optional[TeamTalkInstance], _: callable, app_cfg: Any) -> str: # Added app_cfg
    server_name = app_cfg.SERVER_NAME # Use passed app_cfg
    if not server_name:
        if tt_instance and tt_instance.connected:
            try:
                server_name = ttstr(tt_instance.server.get_properties().server_name)
                if not server_name: # Check if empty string after ttstr
                    server_name = _("Unknown Server")
            except (TimeoutError, pytalk.exceptions.TeamTalkException) as e:
                logger.error(f"Error getting server name from TT instance {tt_instance.server_info.host if tt_instance.server_info else 'N/A'}: {e}")
                server_name = _("Unknown Server")
            except Exception as e_unexp: # Catch any other unexpected error
                logger.error(f"Unexpected error getting server name from TT instance {tt_instance.server_info.host if tt_instance.server_info else 'N/A'}: {e_unexp}", exc_info=True)
                server_name = _("Unknown Server")
        else:
            server_name = _("Unknown Server")
    return server_name if server_name else _("Unknown Server") # Ensure non-empty return

def get_tt_user_display_name(user: TeamTalkUser, translator_gettext_func: callable) -> str: # Changed translator to translator_gettext_func
    # This function seems fine, uses passed translator.
    display_name = ttstr(user.nickname)
    if not display_name:
        display_name = ttstr(user.username)
    if not display_name: # Ensure display_name is not empty after trying nickname and username
        display_name = translator_gettext_func("unknown user") # Use the passed gettext func
    return display_name

def get_username_as_str(user_or_account: Union[TeamTalkUser, TeamTalkUserAccount]) -> str:
    # This function is fine as is.
    username = None
    if hasattr(user_or_account, 'username'): username = user_or_account.username
    elif hasattr(user_or_account, '_account') and hasattr(user_or_account._account, 'szUsername'): username = user_or_account._account.szUsername
    elif hasattr(user_or_account, 'szUsername'): username = user_or_account.szUsername
    if isinstance(username, bytes): return ttstr(username)
    return str(username) if username is not None else ""

def build_help_message(_: callable, platform: str, is_telegram_admin: bool, is_teamtalk_admin: bool) -> str:
    # This function is fine as is, relies on passed parameters.
    parts = []
    if platform == "telegram":
        parts.append(_("<b>Available Commands:</b>"))
        parts.append(_("/who - Show online users.\n"
                       "/settings - Access the interactive settings menu (language, notifications, mute lists, NOON feature).\n"
                       "/help - Show this help message.\n"
                       "(Note: `/start` is used to initiate the bot and process deeplinks.)"))
        if is_telegram_admin:
            parts.append(_("\n<b>Admin Commands:</b>"))
            parts.append(_("/kick - Kick a user from the server (via buttons).\n"
                           "/ban - Ban a user from the server (via buttons).\n"
                           "/subscribers - View and manage subscribed users."))
    elif platform == "teamtalk":
        parts.append(_("Available commands:"))
        parts.append(_("/sub - Get a link to subscribe to notifications.\n"
                       "/unsub - Get a link to unsubscribe from notifications.\n"
                       "/help - Show help."))
        if is_teamtalk_admin:
            parts.append(_("\nAdmin commands (MAIN_ADMIN from config only):"))
            parts.append(_("/add_admin <Telegram ID> [<Telegram ID>...] - Add bot admin.\n"
                           "/remove_admin <Telegram ID> [<Telegram ID>...] - Remove bot admin."))
    return "\n".join(parts)

async def get_online_teamtalk_users(tt_instance: TeamTalkInstance) -> List[TeamTalkUser]: # Changed TeamTalk5 to TeamTalkInstance
    """
    Retrieves a list of online users directly from the provided TeamTalk instance.

    Args:
        tt_instance: The active TeamTalkInstance.

    Returns:
        A list of TeamTalkUser objects representing online users.
        Returns an empty list if the instance is invalid or an error occurs.
    """
    if not tt_instance or not hasattr(tt_instance, 'server') or not hasattr(tt_instance.server, 'get_users'):
        logger.error("get_online_teamtalk_users: Invalid tt_instance or server object.")
        return []
    try:
        # Assuming tt_instance.server.get_users() is the correct way to get users
        # from a pytalk.instance.TeamTalkInstance object.
        # This might be tt_instance.getChannelUsers(0) for all users on server,
        # or tt_instance.server.get_users() if server object has this method.
        # Based on TeamTalkConnection._periodic_cache_sync, it's tt_instance.server.get_users()
        online_users = tt_instance.server.get_users()
        return list(online_users) if online_users else []
    except Exception as e:
        logger.error(f"Error fetching online users from tt_instance ({tt_instance.server_info.host if tt_instance.server_info else 'N/A'}): {e}", exc_info=True)
        return []
