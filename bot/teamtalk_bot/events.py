import logging
import asyncio
from datetime import datetime

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.channel import Channel as PytalkChannel
from pytalk.user import User as TeamTalkUser
from pytalk.enums import UserStatusMode

from bot.config import app_config
from bot.database.engine import SessionFactory
from bot.core.notifications import send_join_leave_notification_logic
from bot.core.user_settings import USER_SETTINGS_CACHE # For admin lang in on_message
from bot.constants import (
    DEFAULT_LANGUAGE, TEAMTALK_PRIVATE_MESSAGE_TYPE,
    NOTIFICATION_EVENT_JOIN, NOTIFICATION_EVENT_LEAVE
)

# Import bot_instance variables carefully
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.teamtalk_bot.utils import (
    _tt_reconnect,
    _tt_rejoin_channel,
    forward_tt_message_to_telegram_admin
)
from bot.teamtalk_bot.commands import (
    handle_tt_subscribe_command,
    handle_tt_unsubscribe_command,
    handle_tt_add_admin_command,
    handle_tt_remove_admin_command,
    handle_tt_help_command,
    handle_tt_unknown_command as handle_tt_unknown_command_specific, # Renamed to avoid clash
)


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

@tt_bot_module.tt_bot.event # Decorate with the bot instance from its module
async def on_ready():
    """
    Called when the Pytalk bot is ready to start connecting to servers.
    This is where we add the server configuration.
    """
    # Use global current_tt_instance, login_complete_time from tt_bot_module
    server_info_obj = pytalk.TeamTalkServerInfo(
        host=app_config["HOSTNAME"],
        tcp_port=app_config["PORT"],
        udp_port=app_config["PORT"], # Assuming TCP and UDP ports are the same
        username=app_config["USERNAME"],
        password=app_config["PASSWORD"],
        encrypted=app_config["ENCRYPTED"],
        nickname=app_config["NICKNAME"]
        # join_channel_id=app_config.get("CHANNEL_ID_INT", -1), # Пример, если есть такой конфиг
        # join_channel_password=app_config.get("CHANNEL_PASSWORD")
    )
    try:
        tt_bot_module.login_complete_time = None # Reset before connection attempt
        await tt_bot_module.tt_bot.add_server(server_info_obj)
        logger.info(f"Connection process initiated by Pytalk for server: {app_config['HOSTNAME']}.")
    except Exception as e:
        logger.error(f"Error initiating TeamTalk server connection in on_ready: {e}", exc_info=True)
        asyncio.create_task(_tt_reconnect())

@tt_bot_module.tt_bot.event
async def on_my_login(server: PytalkServer):
    tt_instance_val = server.teamtalk_instance
    tt_bot_module.current_tt_instance = tt_instance_val
    tt_bot_module.login_complete_time = None

    server_name = "Unknown Server"
    try:
        server_props = tt_instance_val.server.get_properties()
        if server_props:
            server_name = ttstr(server_props.server_name)
    except Exception as e_prop:
        logger.warning(f"Could not get server name on login: {e_prop}")

    logger.info(f"Successfully logged in to TeamTalk server: {server_name} ({ttstr(server.info.host)})")

    try:
        channel_id_or_path_val = app_config["CHANNEL"]
        channel_id_val = -1
        target_channel_name_log = channel_id_or_path_val # For logging

        if channel_id_or_path_val.isdigit():
            channel_id_val = int(channel_id_or_path_val)
            # Optionally resolve name for logging
            chan_obj_log = tt_instance_val.get_channel(channel_id_val)
            if chan_obj_log: target_channel_name_log = ttstr(chan_obj_log.name)
        else: # Assume it's a path
            channel_obj_val = tt_instance_val.get_channel_from_path(channel_id_or_path_val)
            if channel_obj_val:
                channel_id_val = channel_obj_val.id
                target_channel_name_log = ttstr(channel_obj_val.name)
            else:
                logger.error(f"Channel path '{channel_id_or_path_val}' not found during login.")
                # Decide if bot should stay in root or attempt rejoin later. For now, stays in root.

        if channel_id_val != -1:
            logger.info(f"Attempting to join channel: '{target_channel_name_log}' (Resolved ID: {channel_id_val})")
            tt_instance_val.join_channel_by_id(channel_id_val, password=app_config.get("CHANNEL_PASSWORD"))
            await asyncio.sleep(1) # Allow time for join to process
        else:
            logger.warning(f"Could not resolve channel '{app_config['CHANNEL']}' to an ID during login. Bot will remain in current channel (likely root).")

        tt_instance_val.change_status(UserStatusMode.ONLINE, app_config["STATUS_TEXT"])
        logger.info(f"TeamTalk status set to: '{app_config['STATUS_TEXT']}'")
        tt_bot_module.login_complete_time = datetime.utcnow() # Mark login sequence as complete
        logger.info(f"TeamTalk login sequence complete at {tt_bot_module.login_complete_time}.")

    except Exception as e:
        logger.error(f"Error during on_my_login (joining channel/setting status): {e}", exc_info=True)
        if tt_instance_val: # If instance exists, try to rejoin channel if that part failed
            asyncio.create_task(_tt_rejoin_channel(tt_instance_val))


@tt_bot_module.tt_bot.event
async def on_my_connection_lost(server: PytalkServer):
    """Called when the connection to the TeamTalk server is lost."""
    host = ttstr(server.info.host) if server and server.server_info else "Unknown Host"
    logger.warning(f"Connection lost to TeamTalk server {host}. Attempting to reconnect...")
    if tt_bot_module.current_tt_instance and tt_bot_module.current_tt_instance.server_info.host == host:
        tt_bot_module.current_tt_instance = None
        tt_bot_module.login_complete_time = None
    asyncio.create_task(_tt_reconnect())


@tt_bot_module.tt_bot.event
async def on_my_kicked_from_channel(channel_obj: PytalkChannel):
    """Called when the bot is kicked from a channel or the server."""
    tt_instance_val = channel_obj.teamtalk # Get instance from channel
    # tt_bot_module.current_tt_instance should ideally be this instance.

    if not tt_instance_val:
        logger.error("Kicked from channel/server, but PytalkChannel has no TeamTalkInstance. Cannot process reliably.")
        # Fallback to generic reconnect
        tt_bot_module.current_tt_instance = None
        tt_bot_module.login_complete_time = None
        asyncio.create_task(_tt_reconnect())
        return

    try:
        channel_id_val = channel_obj.id
        channel_name_val = ttstr(channel_obj.name) if channel_obj.name else "Unknown Channel"
        server_host = ttstr(tt_instance_val.server_info.host)

        if channel_id_val == 0: # ID 0 often means kicked from the server itself
            logger.warning(f"Kicked from TeamTalk server {server_host} (received channel ID 0). Attempting to reconnect...")
            if tt_bot_module.current_tt_instance == tt_instance_val:
                tt_bot_module.current_tt_instance = None
                tt_bot_module.login_complete_time = None
            asyncio.create_task(_tt_reconnect())
        elif channel_id_val > 0: # Kicked from a specific channel
            logger.warning(f"Kicked from TeamTalk channel '{channel_name_val}' (ID: {channel_id_val}) on server {server_host}. Attempting to rejoin configured channel...")
            # Rejoin the configured main channel, not necessarily the one kicked from
            asyncio.create_task(_tt_rejoin_channel(tt_instance_val))
        else: # Unexpected channel ID
            logger.error(f"Received unexpected kick event from server {server_host} with channel ID: {channel_id_val}. Attempting full reconnect.")
            if tt_bot_module.current_tt_instance == tt_instance_val:
                tt_bot_module.current_tt_instance = None
                tt_bot_module.login_complete_time = None
            asyncio.create_task(_tt_reconnect())

    except Exception as e:
        channel_id_for_log = getattr(channel_obj, 'id', 'unknown_id')
        logger.error(f"Error handling on_my_kicked_from_channel (channel ID: {channel_id_for_log}): {e}", exc_info=True)
        # Generic fallback if anything above fails
        if tt_bot_module.current_tt_instance == tt_instance_val:
            tt_bot_module.current_tt_instance = None
            tt_bot_module.login_complete_time = None
        asyncio.create_task(_tt_reconnect())


@tt_bot_module.tt_bot.event
async def on_message(message: TeamTalkMessage):
    """Called when a new message is received in TeamTalk."""
    # Ensure current_tt_instance is set and message is not from self, and is a private text message
    if not tt_bot_module.current_tt_instance or \
       message.from_id == tt_bot_module.current_tt_instance.getMyUserID() or \
       message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE: # Ensure it's a private text message (type 1)
        return

    sender_username = ttstr(message.user.username)
    message_content = message.content.strip() # Strip whitespace for command checking

    logger.info(f"Received private TT message from {sender_username}: '{message_content[:100]}...'")

    # Determine language for bot's replies in TT (e.g., admin's language or a default)
    # This could be configurable or based on the TT user if linked. For now, use admin's or default.
    bot_reply_language = DEFAULT_LANGUAGE
    if app_config.get("TG_ADMIN_CHAT_ID"):
        admin_settings = USER_SETTINGS_CACHE.get(app_config["TG_ADMIN_CHAT_ID"])
        if admin_settings:
            bot_reply_language = admin_settings.language

    async with SessionFactory() as session: # Create a new session for this event
        if message_content.lower().startswith("/sub"):
            await handle_tt_subscribe_command(message, session, bot_reply_language)
        elif message_content.lower().startswith("/unsub"):
            await handle_tt_unsubscribe_command(message, session, bot_reply_language)
        elif message_content.lower().startswith("/add_admin"):
            await handle_tt_add_admin_command(message, session, bot_reply_language)
        elif message_content.lower().startswith("/remove_admin"):
            await handle_tt_remove_admin_command(message, session, bot_reply_language)
        elif message_content.lower().startswith("/help"):
            await handle_tt_help_command(message, bot_reply_language)
        elif message_content.startswith("/"): # An unknown command
            await handle_tt_unknown_command_specific(message, bot_reply_language)
        else: # Not a command, forward to Telegram admin if configured
            await forward_tt_message_to_telegram_admin(message, tt_bot_module.current_tt_instance)


@tt_bot_module.tt_bot.event
async def on_user_login(user: TeamTalkUser):
    """Called when a user logs into the server."""
    tt_instance = user.server.teamtalk_instance # Get instance from user object
    if tt_instance:
        await send_join_leave_notification_logic(NOTIFICATION_EVENT_JOIN, user, tt_instance)
    else:
        logger.warning(f"on_user_login: Could not get TeamTalkInstance from user {ttstr(user.username)}. Skipping notification.")


@tt_bot_module.tt_bot.event
async def on_user_logout(user: TeamTalkUser):
    """Called when a user logs out from the server."""
    tt_instance = user.server.teamtalk_instance
    if tt_instance:
        await send_join_leave_notification_logic(NOTIFICATION_EVENT_LEAVE, user, tt_instance)
    else:
        logger.warning(f"on_user_logout: Could not get TeamTalkInstance from user {ttstr(user.username)}. Skipping notification.")

# Add other TeamTalk events here if needed, e.g.:
# @tt_bot_module.tt_bot.event
# async def on_channel_new(channel: PytalkChannel): ...
# @tt_bot_module.tt_bot.event
# async def on_user_channel_join(user: PytalkUser, channel: PytalkChannel): ...
# @tt_bot_module.tt_bot.event
# async def on_user_channel_leave(user: PytalkUser, channel: PytalkChannel): ...
