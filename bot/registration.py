"""Centralized registration for command and event handlers."""

import logging

from dishka import AsyncContainer

from bot.command_bus.bus import CommandBus
from bot.command_handlers.teamtalk_handlers import TeamTalkCommandHandlers
from bot.commands import (
    BanUserCommand,
    GetAllTeamTalkAccountsCommand,
    GetOnlineUsersCommand,
    KickUserCommand,
)
from bot.event_bus.bus import EventBus
from bot.event_handlers.teamtalk_replier import TeamTalkReplyHandler
from bot.event_handlers.telegram_notifier import TelegramNotificationHandler
from bot.teamtalk_bot.events import (
    AdminStatusChangedEvent,
    PrivateMessageReceivedEvent,
    ReplyToTeamTalkUserEvent,
    UserJoinedEvent,
    UserLeftEvent,
)

logger = logging.getLogger(__name__)


async def register_all_handlers(
    command_bus: CommandBus, event_bus: EventBus, container: AsyncContainer
) -> None:
    """Get all handler instances from the DI container and register them.

    Args:
        command_bus: The command bus instance.
        event_bus: The event bus instance.
        container: The dishka container instance.
    """
    # Get handlers from the container
    # This ensures they are created with all their dependencies
    tt_handlers = await container.get(TeamTalkCommandHandlers)
    telegram_handler = await container.get(TelegramNotificationHandler)
    teamtalk_replier = await container.get(TeamTalkReplyHandler)

    # Register command handlers
    command_bus.register(GetOnlineUsersCommand, tt_handlers.get_online_users)
    command_bus.register(KickUserCommand, tt_handlers.kick_user)
    command_bus.register(BanUserCommand, tt_handlers.ban_user)
    command_bus.register(GetAllTeamTalkAccountsCommand, tt_handlers.get_all_tt_accounts)
    logger.info("Command handlers registered.")

    # Register event handlers (subscribers)
    event_bus.subscribe(UserJoinedEvent, telegram_handler.handle_user_joined)
    event_bus.subscribe(UserLeftEvent, telegram_handler.handle_user_left)
    event_bus.subscribe(
        PrivateMessageReceivedEvent, telegram_handler.handle_private_message
    )
    event_bus.subscribe(
        AdminStatusChangedEvent, telegram_handler.handle_admin_status_changed
    )
    event_bus.subscribe(ReplyToTeamTalkUserEvent, teamtalk_replier.handle_reply_event)
    logger.info("Event handlers subscribed.")
