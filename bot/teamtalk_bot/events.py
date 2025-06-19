import logging
import asyncio
from datetime import datetime

import pytalk
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.channel import Channel as PytalkChannel
from pytalk.user import User as TeamTalkUser
from pytalk.enums import Status

from bot.config import app_config
from bot.language import get_translator
from bot.database.engine import SessionFactory
from bot.core.notifications import send_join_leave_notification_logic
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.constants import (
    DEFAULT_LANGUAGE,
    TEAMTALK_PRIVATE_MESSAGE_TYPE,
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    RECONNECT_CHECK_INTERVAL_SECONDS,
)

from bot.state import ONLINE_USERS_CACHE, USER_ACCOUNTS_CACHE
from aiogram.filters import CommandObject

from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.teamtalk_bot.utils import (
    _tt_reconnect,
    _tt_rejoin_channel,
    forward_tt_message_to_telegram_admin,
)
from bot.teamtalk_bot.commands import (
    handle_tt_subscribe_command,
    handle_tt_unsubscribe_command,
    handle_tt_add_admin_command,
    handle_tt_remove_admin_command,
    handle_tt_help_command,
    handle_tt_unknown_command as handle_tt_unknown_command_specific,
)

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr

async def _periodic_cache_sync(tt_instance: pytalk.instance.TeamTalkInstance):
    """Periodically synchronizes the ONLINE_USERS_CACHE with the server's state."""
    sync_interval_seconds = 300
    while True:
        try:
            if tt_instance and tt_instance.connected and tt_instance.logged_in:
                logger.debug("Performing periodic cache synchronization...")
                server_users = tt_instance.server.get_users()
                new_cache = {user.id: user for user in server_users if hasattr(user, 'id')}

                ONLINE_USERS_CACHE.clear()
                ONLINE_USERS_CACHE.update(new_cache)

                logger.debug(f"Cache synchronized. Users online: {len(ONLINE_USERS_CACHE)}")
            else:
                logger.warning("Skipping periodic cache sync: TT instance not ready.")
                await asyncio.sleep(RECONNECT_CHECK_INTERVAL_SECONDS)
                continue

        except Exception as e:
            logger.error(f"Error during periodic cache synchronization: {e}", exc_info=True)
            if tt_instance and tt_instance.connected and tt_instance.logged_in:
                 await asyncio.sleep(60) # Wait 1 minute before retrying if error is with a connected instance

        await asyncio.sleep(sync_interval_seconds)

TT_COMMAND_HANDLERS = {
    "/sub": handle_tt_subscribe_command,
    "/unsub": handle_tt_unsubscribe_command,
    "/add_admin": handle_tt_add_admin_command,
    "/remove_admin": handle_tt_remove_admin_command,
    "/help": handle_tt_help_command,
}


def get_configured_status():
    """Helper function to get the combined status object based on GENDER config."""
    gender = app_config.GENDER
    if gender == "male":
        return Status.online.male
    elif gender == "female":
        return Status.online.female
    else:
        return Status.online.neutral


async def populate_user_accounts_cache(tt_instance):
    logger.info("Performing initial population of the user accounts cache...")
    try:
        all_accounts = await tt_instance.list_user_accounts()
        USER_ACCOUNTS_CACHE.clear()
        for acc in all_accounts:
            username = acc.username
            if isinstance(username, bytes):
                username_str = ttstr(username)
            else:
                username_str = str(username)

            if username_str:
                USER_ACCOUNTS_CACHE[username_str] = acc
        logger.debug(f"User accounts cache populated with {len(USER_ACCOUNTS_CACHE)} accounts.")
    except Exception as e:
        logger.error(f"Failed to populate user accounts cache: {e}", exc_info=True)


async def _initiate_reconnect(reason: str):
    logger.warning(reason)
    ONLINE_USERS_CACHE.clear()
    USER_ACCOUNTS_CACHE.clear()
    logger.info("Online users and user accounts caches have been cleared due to reconnection.")

    if tt_bot_module.current_tt_instance is not None:
        logger.debug(f"Resetting current_tt_instance and login_complete_time due to: {reason}")
        tt_bot_module.current_tt_instance = None
        tt_bot_module.login_complete_time = None
    else:
        logger.debug(f"current_tt_instance was already None when _initiate_reconnect was called for: {reason}")

    asyncio.create_task(_tt_reconnect())


async def _finalize_bot_login_sequence(tt_instance: pytalk.instance.TeamTalkInstance, channel: PytalkChannel):
    """Handles the final steps of the bot's login and initialization sequence."""
    channel_name_display = ttstr(channel.name) if hasattr(channel, "name") and isinstance(channel.name, bytes) else str(channel.name)
    logger.info(f"Bot successfully joined channel: {channel_name_display}")

    logger.info("Performing initial population of the online users cache...")
    try:
        initial_online_users = tt_instance.server.get_users()
        ONLINE_USERS_CACHE.clear()
        for u in initial_online_users:
            if hasattr(u, "id"):
                ONLINE_USERS_CACHE[u.id] = u
            else:
                # Log if a user object from server.get_users() doesn't have an ID.
                username_str = ttstr(u.username) if hasattr(u, 'username') else 'UnknownUserWithoutID'
                logger.warning(f"User object '{username_str}' missing 'id' attribute during initial cache population. Skipping.")
        logger.info(f"ONLINE_USERS_CACHE initialized with {len(ONLINE_USERS_CACHE)} users.")
    except Exception as e:
        logger.error(f"Error during initial population of online users cache: {e}", exc_info=True)

    asyncio.create_task(populate_user_accounts_cache(tt_instance))

    if not hasattr(tt_instance, '_periodic_sync_task_running') or not tt_instance._periodic_sync_task_running:
        asyncio.create_task(_periodic_cache_sync(tt_instance))
        tt_instance._periodic_sync_task_running = True
        logger.info("Periodic cache synchronization task started.")
    else:
        logger.info("Periodic cache synchronization task already running for this instance.")

    try:
        configured_status = get_configured_status()
        tt_instance.change_status(configured_status, app_config.STATUS_TEXT)
        tt_bot_module.login_complete_time = datetime.utcnow()
        logger.debug(f"TeamTalk status set to: '{app_config.STATUS_TEXT}'")
        logger.info(f"TeamTalk login sequence finalized at {tt_bot_module.login_complete_time}.")
    except Exception as e:
        logger.error(f"Error setting status or login_complete_time for bot: {e}", exc_info=True)


@tt_bot_module.tt_bot.event
async def on_ready():
    server_info_obj = pytalk.TeamTalkServerInfo(
        host=app_config.HOSTNAME,
        tcp_port=app_config.PORT,
        udp_port=app_config.PORT,
        username=app_config.USERNAME,
        password=app_config.PASSWORD,
        encrypted=app_config.ENCRYPTED,
        nickname=app_config.NICKNAME,
    )
    try:
        tt_bot_module.login_complete_time = None
        await tt_bot_module.tt_bot.add_server(server_info_obj)
        logger.info(f"Connection process initiated by Pytalk for server: {app_config.HOSTNAME}.")
    except Exception as e:
        logger.error(f"Error initiating TeamTalk server connection in on_ready: {e}", exc_info=True)
        asyncio.create_task(_tt_reconnect())


@tt_bot_module.tt_bot.event
async def on_my_login(server: PytalkServer):
    tt_instance = server.teamtalk_instance
    tt_bot_module.current_tt_instance = tt_instance
    tt_bot_module.login_complete_time = None
    tt_instance._periodic_sync_task_running = False # Reset flag on new login

    server_name = "Unknown Server"
    try:
        server_props = tt_instance.server.get_properties()
        if server_props:
            server_name = ttstr(server_props.server_name)
    except Exception as e_prop:
        logger.warning(f"Could not get server name on login: {e_prop}")

    logger.info(f"Successfully logged in to TeamTalk server: {server_name} ({server.info.host})")

    try:
        channel_id_or_path = app_config.CHANNEL
        channel_id = -1
        target_channel_name_log = channel_id_or_path

        if channel_id_or_path.isdigit():
            channel_id = int(channel_id_or_path)
            chan_obj_log = tt_instance.get_channel(channel_id)
            if chan_obj_log:
                target_channel_name_log = ttstr(chan_obj_log.name)
        else:
            channel_obj = tt_instance.get_channel_from_path(channel_id_or_path)
            if channel_obj:
                channel_id = channel_obj.id
                target_channel_name_log = ttstr(channel_obj.name)
            else:
                logger.error(f"Channel path '{channel_id_or_path}' not found during login.")

        if channel_id != -1:
            logger.info(f"Attempting to join channel: '{target_channel_name_log}' (Resolved ID: {channel_id})")
            tt_instance.join_channel_by_id(channel_id, password=app_config.CHANNEL_PASSWORD)
        else:
            logger.warning(
                f"Could not resolve channel '{app_config.CHANNEL}' or no channel configured. Bot remains in current/root channel."
            )
            current_channel_id = tt_instance_val.getMyCurrentChannelID()
            current_channel_obj = tt_instance_val.get_channel(current_channel_id)
            if current_channel_obj:
                 logger.info(f"Bot already in channel '{ttstr(current_channel_obj.name)}' on login, ensuring finalization.")
                 pass

    except Exception as e:
        logger.error(f"Error during on_my_login (joining channel/setting status): {e}", exc_info=True)
        if tt_instance:
            asyncio.create_task(_tt_rejoin_channel(tt_instance))


@tt_bot_module.tt_bot.event
async def on_my_connection_lost(server: PytalkServer):
    if tt_bot_module.current_tt_instance and hasattr(tt_bot_module.current_tt_instance, '_periodic_sync_task_running'):
        tt_bot_module.current_tt_instance._periodic_sync_task_running = False # Allow new task on reconnect
    await _initiate_reconnect("Connection lost to TeamTalk server. Attempting to reconnect...")


@tt_bot_module.tt_bot.event
async def on_my_kicked_from_channel(channel_obj: PytalkChannel):
    tt_instance = channel_obj.teamtalk
    if hasattr(tt_instance, '_periodic_sync_task_running'):
        tt_instance._periodic_sync_task_running = False # Allow new task if we rejoin and finalize

    if not tt_instance:
        await _initiate_reconnect(
            "Kicked from channel/server, but PytalkChannel has no TeamTalkInstance. Cannot process reliably. Initiating full reconnect."
        )
        return

    try:
        channel_id = channel_obj.id
        channel_name = ttstr(channel_obj.name) if channel_obj.name else "Unknown Channel"
        server_host = ttstr(tt_instance.server_info.host)

        if channel_id == 0: # Kicked from server
            await _initiate_reconnect(f"Kicked from TeamTalk server {server_host} (received channel ID 0). Attempting to reconnect...")
        elif channel_id > 0: # Kicked from a specific channel
            logger.warning(
                f"Kicked from TeamTalk channel '{channel_name}' (ID: {channel_id}) on server {server_host}. Attempting to rejoin configured channel..."
            )
            asyncio.create_task(_tt_rejoin_channel(tt_instance))
        else: # Unexpected
            await _initiate_reconnect(
                f"Received unexpected kick event from server {server_host} with channel ID: {channel_id}. Attempting full reconnect."
            )

    except Exception as e:
        channel_id_for_log = getattr(channel_obj, "id", "unknown_id")
        logger.error(f"Error handling on_my_kicked_from_channel (channel ID: {channel_id_for_log}): {e}", exc_info=True)
        await _initiate_reconnect(f"Error handling kick event for channel ID {channel_id_for_log}. Attempting full reconnect.")


@tt_bot_module.tt_bot.event
async def on_message(message: TeamTalkMessage):
    if (
        not tt_bot_module.current_tt_instance
        or message.from_id == tt_bot_module.current_tt_instance.getMyUserID()
        or message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE
    ):
        return

    sender_username = ttstr(message.user.username)
    message_content = message.content.strip()

    logger.debug(f"Received private TT message from {sender_username}: '{message_content[:100]}...'" )

    bot_reply_language = DEFAULT_LANGUAGE
    if app_config.TG_ADMIN_CHAT_ID is not None:
        admin_chat_id_int = app_config.TG_ADMIN_CHAT_ID
        # admin_chat_id_int is already an int, no need for try-except ValueError

        admin_settings = USER_SETTINGS_CACHE.get(admin_chat_id_int)
        if admin_settings:
            bot_reply_language = admin_settings.language

    translator = get_translator(bot_reply_language)
    _ = translator.gettext

    command_parts = message_content.split(maxsplit=1)
    command_name = command_parts[0].lower()
    handler = TT_COMMAND_HANDLERS.get(command_name)

    async with SessionFactory() as session:
        if handler:
            if command_name in ["/add_admin", "/remove_admin"]:
                args_str = command_parts[1] if len(command_parts) > 1 else None
                command_obj = CommandObject(args=args_str)
                await handler(tt_message=message, command=command_obj, session=session, _=_)
            elif command_name == "/help":
                await handler(message, _)
            else:
                await handler(message, session, _)
        elif message_content.startswith("/"):
            await handle_tt_unknown_command_specific(message, _)
        else:
            await forward_tt_message_to_telegram_admin(message)


@tt_bot_module.tt_bot.event
async def on_user_login(user: TeamTalkUser):
    tt_instance = user.server.teamtalk_instance
    if tt_instance:
        ONLINE_USERS_CACHE[user.id] = user
        logger.debug(f"User session {user.id} ({ttstr(user.username)}) added to online cache. Cache size: {len(ONLINE_USERS_CACHE)}")
        await send_join_leave_notification_logic(
            NOTIFICATION_EVENT_JOIN, user, tt_instance, tt_bot_module.login_complete_time
        )
    else:
        logger.warning(f"on_user_login: Could not get TeamTalkInstance from user {ttstr(user.username)}. Skipping notification.")


@tt_bot_module.tt_bot.event
async def on_user_join(user: TeamTalkUser, channel: PytalkChannel):
    """Handles any user joining a channel, with special logic for the bot itself."""
    # Ensure user object has an ID before caching
    if not hasattr(user, 'id') or user.id is None:
        username_str = ttstr(user.username) if hasattr(user, 'username') else 'UnknownUserWithoutID'
        logger.warning(f"User '{username_str}' joined channel but has no valid ID. Cannot add to ONLINE_USERS_CACHE.")
        return
    ONLINE_USERS_CACHE[user.id] = user

    tt_instance = getattr(user.server, "teamtalk_instance", None) or getattr(user, "teamtalk_instance", None)
    if not tt_instance:
        logger.error(f"CRITICAL: Could not retrieve TeamTalk instance in on_user_join for user ID: {user.id}.")
        return

    my_user_id = tt_instance.getMyUserID()
    if my_user_id is None:
        logger.error("CRITICAL: Failed to get bot's own user ID in on_user_join.")
        return

    if user.id == my_user_id:
        await _finalize_bot_login_sequence(tt_instance, channel)


@tt_bot_module.tt_bot.event
async def on_user_logout(user: TeamTalkUser):
    tt_instance = user.server.teamtalk_instance
    if tt_instance:
        if hasattr(user, 'id') and user.id in ONLINE_USERS_CACHE:
            del ONLINE_USERS_CACHE[user.id]
            logger.debug(
                f"User session {user.id} ({ttstr(user.username)}) removed from online cache. Cache size: {len(ONLINE_USERS_CACHE)}"
            )
        elif hasattr(user, 'id'):
            logger.warning(f"User session {user.id} ({ttstr(user.username)}) attempted logout but was not found in ONLINE_USERS_CACHE.")
        else:
            logger.warning(f"User ({ttstr(user.username) if hasattr(user, 'username') else 'UnknownUserWithoutID'}) logged out but has no ID. Cache not modified.")

        await send_join_leave_notification_logic(
            NOTIFICATION_EVENT_LEAVE, user, tt_instance, tt_bot_module.login_complete_time
        )
    else:
        logger.warning(f"on_user_logout: Could not get TeamTalkInstance from user {ttstr(user.username) if hasattr(user, 'username') else 'UnknownUser'}. Skipping notification.")


@tt_bot_module.tt_bot.event
async def on_user_update(user: TeamTalkUser):
    if hasattr(user, 'id') and user.id in ONLINE_USERS_CACHE:
        ONLINE_USERS_CACHE[user.id] = user
        logger.debug(f"User {user.id} updated in cache.")
    elif hasattr(user, 'id'):
        # User might have connected while periodic sync was running and got added by it,
        # but on_user_login event for them might not have fired yet or was missed.
        # So, if they are in cache (likely from periodic sync), we update.
        # If not, we don't add them here as on_user_login should be the primary entry point.
        logger.debug(f"User {user.id} updated but was not initially in ONLINE_USERS_CACHE via event. Update ignored by on_user_update unless already present.")
    else:
        logger.warning(f"User ({ttstr(user.username) if hasattr(user, 'username') else 'UnknownUserWithoutID'}) updated but has no ID. Cache not modified.")

@tt_bot_module.tt_bot.event
async def on_user_account_new(account: "pytalk.UserAccount"):
    username = account.username
    username_str = ttstr(username) if isinstance(username, bytes) else str(username)
    if username_str:
        USER_ACCOUNTS_CACHE[username_str] = account
        logger.debug(f"New user account '{username_str}' added to cache. Cache size: {len(USER_ACCOUNTS_CACHE)}")


@tt_bot_module.tt_bot.event
async def on_user_account_remove(account: "pytalk.UserAccount"):
    username = account.username
    username_str = ttstr(username) if isinstance(username, bytes) else str(username)
    if username_str and username_str in USER_ACCOUNTS_CACHE:
        del USER_ACCOUNTS_CACHE[username_str]
        logger.debug(f"User account '{username_str}' removed from cache. Cache size: {len(USER_ACCOUNTS_CACHE)}")
