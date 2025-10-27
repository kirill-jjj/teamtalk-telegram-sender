"""Defines domain events specific to the TeamTalk bot."""

from __future__ import annotations

import pytalk  # noqa: TC002

from bot.event_bus.types import BaseEvent


class UserJoinedEvent(BaseEvent):
    """Event published when a user joins the TeamTalk server."""

    user_nickname: str
    username: str
    user_id: int
    server_name: str
    online_users_cache: dict[int, pytalk.user.User]


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
    online_users_cache: dict[int, pytalk.user.User]


class ConnectionEstablishedEvent(BaseEvent):
    """Event published when a TeamTalk connection is successfully established."""

    connection_id: str


class LoginSuccessfulEvent(BaseEvent):
    """Event published when a TeamTalk bot successfully logs in to a server."""

    connection_id: str
