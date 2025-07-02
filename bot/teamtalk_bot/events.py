import logging
import asyncio
from datetime import datetime

import pytalk
from pytalk.exceptions import PermissionError as PytalkPermissionError, TeamTalkException as PytalkException
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
)

from bot.state import ONLINE_USERS_CACHE, USER_ACCOUNTS_CACHE
from aiogram.filters import CommandObject
from bot.core.languages import Language

from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.teamtalk_bot.utils import (
    initiate_reconnect_task,
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
    while True:
        try:
            if tt_instance and tt_instance.connected and tt_instance.logged_in:
                logger.debug("Performing periodic online users cache synchronization...")
                server_users = tt_instance.server.get_users()
                new_cache = {user.id: user for user in server_users if hasattr(user, 'id')}

                ONLINE_USERS_CACHE.clear()
                ONLINE_USERS_CACHE.update(new_cache)

                logger.debug(f"Online users cache synchronized. Users online: {len(ONLINE_USERS_CACHE)}.")
            else:
                logger.warning("Skipping periodic online users cache sync: TT instance not ready.")
                await asyncio.sleep(app_config.TT_RECONNECT_CHECK_INTERVAL_SECONDS)
                continue

        except TimeoutError as e_timeout:
            logger.error(f"TimeoutError during periodic online users cache synchronization: {e_timeout}.", exc_info=True)
            # Use a fraction of the main sync interval for retry after timeout
            await asyncio.sleep(app_config.ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS // 2)
        except PytalkException as e_pytalk:
            logger.error(f"Pytalk specific error during periodic online users cache sync: {e_pytalk}.", exc_info=True)
            if tt_instance and tt_instance.connected and tt_instance.logged_in:
                await asyncio.sleep(60) # Keep a fixed shorter delay for pytalk errors before next full interval
        except Exception as e:
            logger.error(f"Error during periodic online users cache synchronization: {e}.", exc_info=True)
            if tt_instance and tt_instance.connected and tt_instance.logged_in:
                 await asyncio.sleep(60) # Keep a fixed shorter delay for general errors

        await asyncio.sleep(app_config.ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS)

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
    logger.info("Performing initial population of user accounts cache...")
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
        logger.info(f"Successfully populated user accounts cache with {len(USER_ACCOUNTS_CACHE)} accounts.")
    except TimeoutError as e_timeout:
        logger.error(f"TimeoutError populating user accounts cache: {e_timeout}.", exc_info=True)
    except PytalkException as e_pytalk: # Covers TeamTalkException
        logger.error(f"Pytalk specific error populating user accounts cache: {e_pytalk}.", exc_info=True)
    except pytalk.exceptions.PermissionError as e_perm: # More specific Pytalk error
        logger.error(f"Pytalk PermissionError populating user accounts cache: {e_perm}.", exc_info=True)
    except ValueError as e_val: # ValueError from pytalk.instance
        logger.error(f"ValueError populating user accounts cache (from pytalk): {e_val}.", exc_info=True)
    except Exception as e: # General fallback
        logger.error(f"Failed to populate user accounts cache with an unexpected error: {e}.", exc_info=True)


async def _finalize_bot_login_sequence(tt_instance: pytalk.instance.TeamTalkInstance, channel: PytalkChannel):
    """Handles the final steps of the bot's login and initialization sequence."""
    channel_name_display = ttstr(channel.name) if hasattr(channel, "name") and isinstance(channel.name, bytes) else str(channel.name)
    logger.info(f"Bot successfully joined channel: {channel_name_display}.")

    logger.info("Performing initial population of online users cache...")
    try:
        initial_online_users = tt_instance.server.get_users()
        ONLINE_USERS_CACHE.clear()
        for u in initial_online_users:
            if hasattr(u, "id"):
                ONLINE_USERS_CACHE[u.id] = u
            else:
                username_str = ttstr(u.username) if hasattr(u, 'username') else 'UnknownUserWithoutID'
                logger.warning(f"User object '{username_str}' missing 'id' attribute during initial online users cache population. Skipping.")
        logger.info(f"Online users cache initialized with {len(ONLINE_USERS_CACHE)} users.")
    except TimeoutError as e_timeout:
        logger.error(f"TimeoutError during initial population of online users cache: {e_timeout}.", exc_info=True)
    except PytalkException as e_pytalk:
        logger.error(f"Pytalk specific error during initial population of online users cache: {e_pytalk}.", exc_info=True)
    except Exception as e:
        logger.error(f"Error during initial population of online users cache: {e}.", exc_info=True)

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
        logger.debug(f"TeamTalk status set to: '{app_config.STATUS_TEXT}'.")
        logger.info(f"TeamTalk login sequence finalized at {tt_bot_module.login_complete_time}.")
    except PytalkPermissionError as e_perm:
        logger.error(f"Pytalk PermissionError setting status for bot: {e_perm}.", exc_info=True)
    except PytalkException as e_pytalk:
        logger.error(f"Pytalk specific error setting status for bot: {e_pytalk}.", exc_info=True)
    except Exception as e:
        logger.error(f"Error setting status or login_complete_time for bot: {e}.", exc_info=True)


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
        logger.info(f"Connection process initiated for server: {app_config.HOSTNAME}.")
    # ------------ ИЗМЕНЕНИЯ ЗДЕСЬ ------------
    # Конкретизируем обработку ошибок, которые может вызвать add_server (включая connect и login)
    except PytalkPermissionError as e_perm:
        logger.critical(f"Pytalk PermissionError during server connection attempt: {e_perm}.", exc_info=True)
        # В этом случае реконнект не имеет смысла, так как данные для входа неверны
    except ValueError as e_val:
        logger.critical(f"ValueError (likely invalid server_info) during server connection attempt: {e_val}.", exc_info=True)
    except TimeoutError as e_timeout:
        logger.error(f"TimeoutError during server connection attempt: {e_timeout}.", exc_info=True)
        initiate_reconnect_task(None)
    except PytalkException as e_pytalk:
        logger.error(f"Pytalk specific error during server connection attempt: {e_pytalk}.", exc_info=True)
        initiate_reconnect_task(None)
    except Exception as e:
        logger.critical(f"Generic UNEXPECTED error initiating TeamTalk server connection: {e}.", exc_info=True)
        initiate_reconnect_task(None)


@tt_bot_module.tt_bot.event
async def on_my_login(server: PytalkServer):
    tt_instance = server.teamtalk_instance
    tt_bot_module.current_tt_instance = tt_instance
    tt_bot_module.login_complete_time = None
    tt_instance._periodic_sync_task_running = False

    server_name = "Unknown Server"
    try:
        server_props = tt_instance.server.get_properties()
        if server_props:
            server_name = ttstr(server_props.server_name)
    except TimeoutError as e_timeout_prop:
        logger.warning(f"TimeoutError getting server properties on login: {e_timeout_prop}.")
    except PytalkException as e_pytalk_prop:
        logger.warning(f"Pytalk specific error getting server properties on login: {e_pytalk_prop}.")
    except Exception as e_prop:
        logger.warning(f"Could not get server properties on login: {e_prop}.")

    logger.info(f"Successfully logged in to TeamTalk server: {server_name} (Host: {server.info.host}).")

    try:
        channel_id_or_path = app_config.CHANNEL
        channel_id = -1
        target_channel_name_log = channel_id_or_path

        if channel_id_or_path.isdigit():
            channel_id = int(channel_id_or_path)
            chan_obj_log = tt_instance.get_channel(channel_id)
            if chan_obj_log:
                target_channel_name_log = ttstr(chan_obj_log.name)
        else: # Path based channel
            channel_obj = tt_instance.get_channel_from_path(channel_id_or_path)
            if channel_obj:
                channel_id = channel_obj.id
                target_channel_name_log = ttstr(channel_obj.name)
            else:
                logger.error(f"Channel path '{channel_id_or_path}' not found during login.")

        if channel_id != -1:
            logger.info(f"Attempting to join channel: '{target_channel_name_log}' (Resolved ID: {channel_id}).")
            tt_instance.join_channel_by_id(channel_id, password=app_config.CHANNEL_PASSWORD)
        else: # No valid channel ID resolved from config
            logger.warning(
                f"Could not resolve channel '{app_config.CHANNEL}' to a valid ID or no channel configured. Bot remains in its current channel."
            )
            current_channel_id = tt_instance.getMyCurrentChannelID()
            current_channel_object = tt_instance.get_channel(current_channel_id)
            if current_channel_object: # Log current channel if bot is in one
                 logger.info(f"Bot currently in channel '{ttstr(current_channel_object.name)}'. Finalization will occur via on_user_join.")

            # ... (логика, если канал не найден, без изменений) ...
            pass
    # ------------ ИЗМЕНЕНИЯ ЗДЕСЬ ------------
    # Конкретизируем обработку ошибок для операций с каналами
    except PytalkPermissionError as e_perm_join:
        logger.error(f"Pytalk PermissionError joining channel '{target_channel_name_log}': {e_perm_join}.", exc_info=True)
    except ValueError as e_val_join:
        logger.error(f"ValueError joining channel '{target_channel_name_log}' (e.g. invalid path/ID): {e_val_join}.", exc_info=True)
    except TimeoutError as e_timeout_join:
         logger.error(f"TimeoutError during channel operations for '{target_channel_name_log}': {e_timeout_join}.", exc_info=True)
         initiate_reconnect_task(tt_instance)
    except PytalkException as e_pytalk_join:
        logger.error(f"Pytalk specific error joining channel '{target_channel_name_log}': {e_pytalk_join}.", exc_info=True)
        initiate_reconnect_task(tt_instance)
    except Exception as e:
        logger.critical(f"Generic UNEXPECTED error during channel joining phase for '{target_channel_name_log}': {e}.", exc_info=True)
        initiate_reconnect_task(tt_instance)


@tt_bot_module.tt_bot.event
async def on_my_connection_lost(server: PytalkServer):
    server_host_display = server.info.host if server and server.info and hasattr(server.info, 'host') else 'Unknown Server'
    logger.warning(f"Connection lost to server {server_host_display}. Initiating reconnection...")
    if tt_bot_module.current_tt_instance and hasattr(tt_bot_module.current_tt_instance, '_periodic_sync_task_running'):
         tt_bot_module.current_tt_instance._periodic_sync_task_running = False
    initiate_reconnect_task(tt_bot_module.current_tt_instance)


@tt_bot_module.tt_bot.event
async def on_my_kicked_from_channel(channel_obj: PytalkChannel):
    tt_instance = channel_obj.teamtalk
    channel_name = ttstr(channel_obj.name) if channel_obj and channel_obj.name else "Unknown Channel"
    channel_id_log = channel_obj.id if channel_obj else "N/A"
    server_host = ttstr(tt_instance.server_info.host) if tt_instance and tt_instance.server_info and hasattr(tt_instance.server_info, 'host') else "Unknown Server"

    logger.warning(f"Kicked from channel '{channel_name}' (ID: {channel_id_log}) on server {server_host}. Initiating full reconnection...")

    if hasattr(tt_instance, '_periodic_sync_task_running'):
        tt_instance._periodic_sync_task_running = False

    initiate_reconnect_task(tt_instance)


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

    logger.debug(f"Received private TT message from {sender_username}: '{message_content[:100]}...'." )

    bot_reply_language = Language.ENGLISH.value
    if app_config.TG_ADMIN_CHAT_ID is not None:
        admin_chat_id_int = app_config.TG_ADMIN_CHAT_ID
        admin_settings = USER_SETTINGS_CACHE.get(admin_chat_id_int)
        if admin_settings:
            bot_reply_language = admin_settings.language.value

    translator = get_translator(bot_reply_language)

    command_parts = message_content.split(maxsplit=1)
    command_name = command_parts[0].lower()
    handler = TT_COMMAND_HANDLERS.get(command_name)

    async with SessionFactory() as session:
        if handler:
            if command_name in ["/add_admin", "/remove_admin"]:
                args_str = command_parts[1] if len(command_parts) > 1 else None
                command_obj = CommandObject(command=command_name, args=args_str)
                await handler(message, command=command_obj, session=session, translator=translator)
            elif command_name == "/help":
                _ = translator.gettext
                await handler(message, _=_)
            else: # For /sub, /unsub or any other future commands that might take session and _
                _ = translator.gettext
                await handler(message, session=session, _=_)
        elif message_content.startswith("/"): # It's a command but not in handlers
            _ = translator.gettext
            await handle_tt_unknown_command_specific(message, _)
        else: # Not a command, forward to admin
            await forward_tt_message_to_telegram_admin(message)


@tt_bot_module.tt_bot.event
async def on_user_login(user: TeamTalkUser):
    tt_instance = user.server.teamtalk_instance
    if tt_instance:
        ONLINE_USERS_CACHE[user.id] = user
        logger.debug(f"User session {user.id} ({ttstr(user.username)}) added to online cache. Cache size: {len(ONLINE_USERS_CACHE)}.")
        await send_join_leave_notification_logic(
            NOTIFICATION_EVENT_JOIN, user, tt_instance, tt_bot_module.login_complete_time
        )
    else:
        logger.warning(f"Could not get TeamTalkInstance from user {ttstr(user.username)} on login. Skipping notification.")


@tt_bot_module.tt_bot.event
async def on_user_join(user: TeamTalkUser, channel: PytalkChannel):
    """Handles any user joining a channel, with special logic for the bot itself."""
    if not hasattr(user, 'id') or user.id is None:
        username_str = ttstr(user.username) if hasattr(user, 'username') else 'UnknownUserWithoutID'
        logger.warning(f"User '{username_str}' joined channel but has no valid ID. Cannot add to online users cache.")
        return
    ONLINE_USERS_CACHE[user.id] = user

    tt_instance = getattr(user.server, "teamtalk_instance", None) or getattr(user, "teamtalk_instance", None)
    if not tt_instance:
        logger.error(f"CRITICAL: Could not retrieve TeamTalk instance in on_user_join for user ID {user.id}. Cannot finalize bot login or process event.")
        return

    my_user_id = tt_instance.getMyUserID()
    if my_user_id is None:
        logger.error("CRITICAL: Failed to get bot's own user ID in on_user_join. Cannot finalize bot login.")
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
                f"User session {user.id} ({ttstr(user.username)}) removed from online cache. Cache size: {len(ONLINE_USERS_CACHE)}."
            )
        elif hasattr(user, 'id'):
            logger.warning(f"User session {user.id} ({ttstr(user.username)}) attempted logout but was not found in online users cache.")
        else:
            logger.warning(f"User ({ttstr(user.username) if hasattr(user, 'username') else 'UnknownUserWithoutID'}) logged out but has no ID. Online users cache not modified.")

        await send_join_leave_notification_logic(
            NOTIFICATION_EVENT_LEAVE, user, tt_instance, tt_bot_module.login_complete_time
        )
    else:
        logger.warning(f"Could not get TeamTalkInstance from user {ttstr(user.username) if hasattr(user, 'username') else 'UnknownUser'} on logout. Skipping notification.")


@tt_bot_module.tt_bot.event
async def on_user_update(user: TeamTalkUser):
    if hasattr(user, 'id') and user.id in ONLINE_USERS_CACHE:
        ONLINE_USERS_CACHE[user.id] = user
        logger.debug(f"User {user.id} updated in online cache.")
    elif hasattr(user, 'id'):
        logger.debug(f"User {user.id} updated but was not initially in online_users_cache. Update ignored by on_user_update unless already present from sync.")
    else:
        logger.warning(f"User ({ttstr(user.username) if hasattr(user, 'username') else 'UnknownUserWithoutID'}) updated but has no ID. Online users cache not modified.")

@tt_bot_module.tt_bot.event
async def on_user_account_new(account: "pytalk.UserAccount"):
    username = account.username
    username_str = ttstr(username) if isinstance(username, bytes) else str(username)
    if username_str:
        USER_ACCOUNTS_CACHE[username_str] = account
        logger.debug(f"New user account '{username_str}' added to accounts cache. Cache size: {len(USER_ACCOUNTS_CACHE)}.")


@tt_bot_module.tt_bot.event
async def on_user_account_remove(account: "pytalk.UserAccount"):
    username = account.username
    username_str = ttstr(username) if isinstance(username, bytes) else str(username)
    if username_str and username_str in USER_ACCOUNTS_CACHE:
        del USER_ACCOUNTS_CACHE[username_str]
        logger.debug(f"User account '{username_str}' removed from accounts cache. Cache size: {len(USER_ACCOUNTS_CACHE)}.")
