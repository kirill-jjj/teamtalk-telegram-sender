import gettext
import logging
from typing import Optional, Union

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from pytalk.user_account import UserAccount as TeamTalkUserAccount

from bot.config import app_config

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

def get_effective_server_name(tt_instance: Optional[TeamTalkInstance], _: callable) -> str:
    server_name = app_config.SERVER_NAME
    if not server_name:
        if tt_instance and tt_instance.connected:
            try:
                server_name = ttstr(tt_instance.server.get_properties().server_name)
                if not server_name:
                    server_name = _("Unknown Server")
            except Exception as e:
                logger.error(f"Error getting server name from TT instance: {e}")
                server_name = _("Unknown Server")
        else:
            server_name = _("Unknown Server")
    return server_name if server_name else _("Unknown Server")

def get_tt_user_display_name(user: TeamTalkUser, translator: "gettext.GNUTranslations") -> str:
    display_name = ttstr(user.nickname)
    if not display_name:
        display_name = ttstr(user.username)
    if not display_name:
        display_name = translator.gettext("unknown user")
    return display_name

def pluralize(number: int, one: str, few: str, many: str) -> str:
    """
    Selects the correct plural form of a word based on the number,
    following Russian language rules.

    Russian pluralization rules:
    - Ends in 1, excluding 11: use 'one' form (e.g., 1, 21, 31)
    - Ends in 2, 3, 4, excluding 12, 13, 14: use 'few' form (e.g., 2, 3, 4, 22, 23, 24)
    - Otherwise: use 'many' form (e.g., 0, 5, 6, 10, 11, 12, 13, 14, 15, 20, 25)
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
    username = None
    if hasattr(user_or_account, 'username'):
        username = user_or_account.username
    elif hasattr(user_or_account, '_account') and hasattr(user_or_account._account, 'szUsername'):
        username = user_or_account._account.szUsername
    elif hasattr(user_or_account, 'szUsername'):
         username = user_or_account.szUsername


    if isinstance(username, bytes):
        return ttstr(username)

    return str(username) if username is not None else ""

def build_help_message(_: callable, platform: str, is_admin: bool, is_bot_admin: bool) -> str:
    """Builds a contextual help message based on platform and user rights."""
    parts = []
    if platform == "telegram":
        parts.append(_("<b>Available Commands:</b>"))
        parts.append(_("/who - Show online users.\n"
                       "/settings - Access the interactive settings menu (language, notifications, mute lists, NOON feature).\n"
                       "/help - Show this help message.\n"
                       "(Note: `/start` is used to initiate the bot and process deeplinks.)"))
        if is_admin:
            parts.append(_("\n<b>Admin Commands:</b>"))
            parts.append(_("/kick - Kick a user from the server (via buttons).\n"
                           "/ban - Ban a user from the server (via buttons).\n"
                           "/subscribers - View and manage subscribed users."))
    elif platform == "teamtalk":
        parts.append(_("Available commands:"))
        parts.append(_("/sub - Get a link to subscribe to notifications and link your TeamTalk account for NOON.\n"
                       "/unsub - Get a link to unsubscribe from notifications.\n"
                       "/help - Show help."))
        if is_bot_admin:
            parts.append(_("\nAdmin commands (MAIN_ADMIN from config only):"))
            parts.append(_("/add_admin <Telegram ID> [<Telegram ID>...] - Add bot admin.\n"
                           "/remove_admin <Telegram ID> [<Telegram ID>...] - Remove bot admin."))

    return "\n".join(parts)
