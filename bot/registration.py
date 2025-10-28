"""Centralized registration for command and event handlers."""

import logging

from dishka import AsyncContainer

from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.events import (
    AdminStatusChangedEvent,
    PrivateMessageReceivedEvent,
    ReplyToTeamTalkUserEvent,
    UserJoinedEvent,
    UserLeftEvent,
)
from bot.teamtalk_bot.handlers.event_bus_subscribers import TeamTalkReplyHandler
from bot.telegram_bot.handlers.event_subscribers import TelegramNotificationHandler

logger = logging.getLogger(__name__)


async def register_all_handlers(event_bus: EventBus, container: AsyncContainer) -> None:
    """Get all handler instances from the DI container and register them.

    Args:
        event_bus: The event bus instance.
        container: The dishka container instance.
    """
    # Get handlers from the container
    # This ensures they are created with all their dependencies
    telegram_handler = await container.get(TelegramNotificationHandler)
    teamtalk_replier = await container.get(TeamTalkReplyHandler)

    # Register event handlers (subscribers)
    event_bus.subscribe(UserJoinedEvent, telegram_handler.on_user_joined)
    event_bus.subscribe(UserLeftEvent, telegram_handler.on_user_left)
    event_bus.subscribe(
        PrivateMessageReceivedEvent, telegram_handler.on_private_message
    )
    event_bus.subscribe(
        AdminStatusChangedEvent, telegram_handler.on_admin_status_changed
    )
    event_bus.subscribe(ReplyToTeamTalkUserEvent, teamtalk_replier.on_reply_event)
    logger.debug("Event handlers subscribed.")
