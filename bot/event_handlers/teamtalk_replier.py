"""Handles sending replies back to TeamTalk users in response to events."""

import logging

import pytalk

from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.events import ReplyToTeamTalkUserEvent

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class TeamTalkReplyHandler:
    """A handler that listens for events and sends replies to TeamTalk."""

    def __init__(self, connections: dict[str, TeamTalkConnection]) -> None:
        """Initializes the TeamTalkReplyHandler."""
        self.connections = connections

    async def on_reply_event(self, event: ReplyToTeamTalkUserEvent) -> None:
        """Handles the ReplyToTeamTalkUserEvent and sends a message."""
        connection = self.connections.get(event.connection_id)
        if not connection or not connection.is_ready:
            logger.error(
                "Cannot reply to TT user: connection %s not found or not ready.",
                event.connection_id,
            )
            return

        if not connection.instance:
            logger.error(
                "Cannot reply to TT user on connection %s: instance is not available.",
                event.connection_id,
            )
            return

        user_to_reply = connection.instance.get_user(event.user_id)
        if user_to_reply:
            try:
                encoded_text = ttstr(event.text)
                user_to_reply.send_message(encoded_text)
                logger.info(
                    "Sent reply to TT user %d on connection %s.",
                    event.user_id,
                    event.connection_id,
                )
            except (
                pytalk.exceptions.PermissionError,
                pytalk.exceptions.TeamTalkException,
                UnicodeEncodeError,
            ):
                logger.exception(
                    "Failed to send reply to TT user %d on connection %s.",
                    event.user_id,
                    event.connection_id,
                )
        else:
            logger.warning(
                "Cannot reply to TT user %d on connection %s: user not found.",
                event.user_id,
                event.connection_id,
            )
