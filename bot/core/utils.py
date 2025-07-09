"""General utility functions for the bot's core logic."""

import gettext
import logging

logger = logging.getLogger(__name__)

# Note: TeamTalk specific utils (get_tt_user_display_name, get_effective_server_name, etc.)
# were moved to bot.teamtalk_bot.utils.py.


def build_help_message(
    translator: gettext.GNUTranslations, platform: str, *, is_telegram_admin: bool, is_teamtalk_admin: bool
) -> str:
    """Builds a help message tailored to the platform and user's admin status.

    Args:
        translator: The gettext translator object.
        platform: The platform for which to generate help ("telegram" or "teamtalk").
        is_telegram_admin: Whether the user is a Telegram admin.
        is_teamtalk_admin: Whether the user is a TeamTalk admin.

    Returns:
        The formatted help message string.
    """
    _ = translator.gettext
    parts = []
    if platform == "telegram":
        parts.append(_("<b>Available Commands:</b>"))
        parts.append(
            _(
                "/who - Show online users.\n"
                "/settings - Access the interactive settings menu "
                "(language, notifications, mute lists, NOON feature).\n"
                "/help - Show this help message.\n"
                "(Note: `/start` is used to initiate the bot and process deeplinks.)"
            )
        )
        if is_telegram_admin:
            parts.append(_("\n<b>Admin Commands:</b>"))
            parts.append(
                _(
                    "/kick - Kick a user from the server (via buttons).\n"
                    "/ban - Ban a user from the server (via buttons).\n"
                    "/subscribers - View and manage subscribed users."
                )
            )
    elif platform == "teamtalk":
        parts.append(_("Available commands:"))
        parts.append(
            _(
                "/sub - Get a link to subscribe to notifications.\n"
                "/unsub - Get a link to unsubscribe from notifications.\n"
                "/help - Show help."
            )
        )
        if is_teamtalk_admin:
            parts.append(_("\nAdmin commands (MAIN_ADMIN from config only):"))
            parts.append(
                _(
                    "/add_admin <Telegram ID> [<Telegram ID>...] - Add bot admin.\n"
                    "/remove_admin <Telegram ID> [<Telegram ID>...] - Remove bot admin."
                )
            )
    return "\n".join(parts)
