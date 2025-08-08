"""Defines domain events specific to the TeamTalk bot."""

from bot.event_bus.types import BaseEvent


class UserJoinedEvent(BaseEvent):
    """Event published when a user joins the TeamTalk server."""

    user_nickname: str
    username: str
    user_id: int
    server_name: str


class PrivateMessageReceivedEvent(BaseEvent):
    """Event published when a private message is received from a user."""

    from_user_id: int
    from_user_nickname: str
    from_user_username: str
    content: str
    server_name: str
    connection_id: str


class ReplyToTeamTalkUserEvent(BaseEvent):
    """Event to command the bot to send a reply back to a TT user."""

    connection_id: str
    user_id: int
    text: str


class AdminStatusChangedEvent(BaseEvent):
    """Event published when a user's admin status changes."""

    telegram_id: int
    is_admin: bool
    lang_code: str | None


class UserLeftEvent(BaseEvent):
    """Event published when a user leaves the TeamTalk server."""

    user_nickname: str
    username: str
    user_id: int
    server_name: str
