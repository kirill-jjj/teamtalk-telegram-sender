import asyncio
import os
import argparse
import traceback # For detailed error reporting before logger is set up
import logging # Added for Application class
from datetime import datetime # Added for Application class Pytalk event handlers

# Standard library imports for Application class
from typing import Dict, Optional, Any

# SQLAlchemy / SQLModel imports
from sqlmodel.ext.asyncio.session import AsyncSession # ДОБАВЬ ЭТУ СТРОКУ
from bot.models import UserSettings # Add this for type hinting
from sqlalchemy.exc import SQLAlchemyError # Add this for exception handling
from sqlmodel import select # Add this for DB operations


# Aiogram imports for Application class
from aiogram import Bot, Dispatcher, html
from aiogram.types import ErrorEvent, Message as AiogramMessage # Renamed to avoid conflict
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

# Pytalk imports for Application class
import pytalk
from pytalk.exceptions import TeamTalkException, PermissionError as PytalkPermissionError # Alias to avoid clash
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.channel import Channel as PytalkChannel
from pytalk.user import User as PytalkUser
from pytalk.enums import Status as PytalkStatus


# Application-specific imports
from bot.logging_setup import setup_logging # Will be called by Application
# Config needs to be imported after env var is set, handled in main_cli
# from bot.config import app_config

from bot.database.engine import SessionFactory
# from bot.core.user_settings import load_user_settings_to_cache, USER_SETTINGS_CACHE # USER_SETTINGS_CACHE might be moved to App # Removed this line
from bot.database import crud
# from bot.state import SUBSCRIBED_USERS_CACHE, ADMIN_IDS_CACHE # These will be instance vars in Application

from bot.core.languages import discover_languages, AVAILABLE_LANGUAGES_DATA, DEFAULT_LANGUAGE_CODE
from bot.language import get_translator # For global error handler

# Telegram specific components to be managed by Application
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message # These will be initialized in Application
from bot.telegram_bot.commands import set_telegram_commands
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    # TeamTalkInstanceMiddleware, # To be replaced/updated
    SubscriptionCheckMiddleware,
    ApplicationMiddleware, # Now created
    ActiveTeamTalkConnectionMiddleware, # Now created
    TeamTalkConnectionCheckMiddleware # Corrected name
)
from bot.telegram_bot.handlers import (
    user_commands_router,
    admin_router,
    callback_router,
    catch_all_router
)
from bot.telegram_bot.handlers.menu_callbacks import menu_callback_router
from bot.telegram_bot.handlers.callback_handlers.subscriber_actions import subscriber_actions_router

# TeamTalk specific components to be managed by Application
from bot.teamtalk_bot.connection import TeamTalkConnection
# from bot.teamtalk_bot.utils import shutdown_tt_instance # This logic will be in Application/TeamTalkConnection
from bot.teamtalk_bot.utils import (
    # initiate_reconnect_task as old_initiate_reconnect_task, # <-- УДАЛИ ЭТУ СТРОКУ
    forward_tt_message_to_telegram_admin, # Will be adapted
)
from bot.teamtalk_bot.commands import ( # These will be adapted to take app/connection
    handle_tt_subscribe_command,
    handle_tt_unsubscribe_command,
    handle_tt_add_admin_command,
    handle_tt_remove_admin_command,
    handle_tt_help_command,
    handle_tt_unknown_command,
)

# Constants used in Pytalk events
from bot.constants import (
    TEAMTALK_PRIVATE_MESSAGE_TYPE,
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    TT_CACHE_SYNC_RETRY_DELAY_SECONDS, # Used in original _periodic_cache_sync
)
from bot.core.notifications import send_join_leave_notification_logic # Will be adapted


logger = logging.getLogger(__name__) # Define logger at module level for Application class

class Application:
    def __init__(self, app_config_instance):
        self.app_config = app_config_instance
        self.logger = setup_logging() # Setup logging once

        self.tg_bot_event: Bot = Bot(token=self.app_config.TG_EVENT_TOKEN)
        self.tg_bot_message: Optional[Bot] = None
        if self.app_config.TG_BOT_MESSAGE_TOKEN:
            self.tg_bot_message = Bot(token=self.app_config.TG_BOT_MESSAGE_TOKEN)
        else:
            self.logger.warning("TG_BOT_MESSAGE_TOKEN not set, message sending capabilities might be limited.")
            self.tg_bot_message = self.tg_bot_event # Fallback to event bot for messages if not specified

        self.dp: Dispatcher = Dispatcher()
        self.tt_bot: pytalk.TeamTalkBot = pytalk.TeamTalkBot(client_name=self.app_config.CLIENT_NAME)

        self.connections: Dict[str, TeamTalkConnection] = {} # Key: server_id (e.g., host:port)
        self.session_factory: SessionFactory = SessionFactory

        self.subscribed_users_cache: set[int] = set()
        self.admin_ids_cache: set[int] = set()
        self.user_settings_cache: Dict[int, Any] = {} # Initialize as empty dict, Any for UserSettings model for now

        self.teamtalk_task: Optional[asyncio.Task] = None
        self._register_pytalk_event_handlers()

    async def load_user_settings_to_app_cache(self): # New method
        """Loads all user settings from DB into the application's cache."""
        # This replaces global load_user_settings_to_cache
        # It directly populates self.user_settings_cache
        # This method in bot.core.user_settings loaded into global USER_SETTINGS_CACHE
        # We need to replicate that logic here for self.user_settings_cache
        async with self.session_factory() as session:
            stmt = select(UserSettings)
            result = await session.execute(stmt)
            all_settings = result.scalars().all()
            for setting in all_settings:
                self.user_settings_cache[setting.telegram_id] = setting
            self.logger.info(f"Loaded {len(self.user_settings_cache)} user settings into app cache.")

    async def get_or_create_user_settings(self, telegram_id: int, session: AsyncSession) -> UserSettings: # New method
        """Gets user settings from app cache or DB, creates if not exists."""
        # This replaces global get_or_create_user_settings
        # It uses self.user_settings_cache and self.session_factory
        cached_settings = self.user_settings_cache.get(telegram_id)
        if cached_settings:
            return cached_settings

        # If not in cache, try DB
        # This logic is from the original bot.core.user_settings.get_or_create_user_settings
        user_settings = await session.get(UserSettings, telegram_id)
        if not user_settings:
            self.logger.info(f"No settings found for user {telegram_id}, creating new ones.")
            user_settings = UserSettings(
                telegram_id=telegram_id,
                language_code=self.app_config.DEFAULT_LANG # Use app_config for default
            )
            session.add(user_settings)
            try:
                await session.commit()
                await session.refresh(user_settings)
                self.logger.info(f"Successfully created and saved new settings for user {telegram_id}.")
            except SQLAlchemyError as e:
                await session.rollback()
                self.logger.error(f"Database error creating settings for user {telegram_id}: {e}", exc_info=True)
                # Should return a default transient UserSettings object or raise
                # For now, consistent with original, it might return None if commit fails,
                # but better to return a default or raise.
                # Let's return a default non-persistent object on error.
                return UserSettings(telegram_id=telegram_id, language_code=self.app_config.DEFAULT_LANG)

        self.user_settings_cache[telegram_id] = user_settings # Add to cache
        return user_settings

    def _get_connection_by_instance(self, tt_instance: pytalk.instance.TeamTalkInstance) -> Optional[TeamTalkConnection]:
        for conn in self.connections.values():
            if conn.instance is tt_instance:
                return conn
        self.logger.warning(f"Could not find an active TeamTalkConnection for instance: {tt_instance}")
        return None

    def _get_connection_by_server_info(self, server_info: pytalk.TeamTalkServerInfo) -> Optional[TeamTalkConnection]:
        # Assuming server_info.host and server_info.tcp_port can uniquely identify a connection
        # This might need adjustment if server_info objects are not stable references or lack unique IDs
        server_key = f"{server_info.host}:{server_info.tcp_port}"
        return self.connections.get(server_key)

    def _register_pytalk_event_handlers(self):
        # Manually register methods as event handlers for self.tt_bot
        # This is instead of using @self.tt_bot.event decorator inside __init__
        # which can be problematic.
        event_handlers = {
            'on_ready': self.on_pytalk_ready,
            'on_my_login': self.on_pytalk_my_login,
            'on_my_connection_lost': self.on_pytalk_my_connection_lost,
            'on_my_kicked_from_channel': self.on_pytalk_my_kicked_from_channel,
            'on_message': self.on_pytalk_message,
            'on_user_login': self.on_pytalk_user_login,
            'on_user_join': self.on_pytalk_user_join,
            'on_user_logout': self.on_pytalk_user_logout,
            'on_user_update': self.on_pytalk_user_update,
            'on_user_account_new': self.on_pytalk_user_account_new,
            'on_user_account_remove': self.on_pytalk_user_account_remove,
            # Add other Pytalk events as needed
        }
        for event_name, handler_method in event_handlers.items():
            setattr(self.tt_bot, event_name, self.tt_bot.event(handler_method))
        self.logger.info("Pytalk event handlers registered.")

    # --- Pytalk Event Handlers (Migrated and adapted) ---
    async def on_pytalk_ready(self):
        """
        Called when self.tt_bot.run() is effectively started.
        This is where we'd initiate connections to configured TeamTalk servers.
        """
        self.logger.info("Pytalk Bot is ready. Initializing TeamTalk connections...")
        # For now, assuming a single server configuration from app_config
        # In a multi-server setup, this would iterate over a list of server configs

        # Create pytalk.TeamTalkServerInfo from app_config
        server_config = self.app_config
        pytalk_server_info = pytalk.TeamTalkServerInfo(
            host=server_config.HOSTNAME,
            tcp_port=server_config.PORT,
            udp_port=server_config.PORT, # Assuming UDP port is same as TCP, adjust if different field in config
            username=server_config.USERNAME,
            password=server_config.PASSWORD,
            encrypted=server_config.ENCRYPTED,
            nickname=server_config.NICKNAME,
            join_channel_id=int(server_config.CHANNEL) if server_config.CHANNEL.isdigit() else -1, # Basic parsing
            join_channel_password=server_config.CHANNEL_PASSWORD or ""
        )

        server_key = f"{pytalk_server_info.host}:{pytalk_server_info.tcp_port}"

        if server_key in self.connections:
            self.logger.warning(f"Connection for {server_key} already exists. Reconnecting.")
            await self.connections[server_key].disconnect_instance() # Clean up old one

        connection = TeamTalkConnection(
            server_info=pytalk_server_info,
            pytalk_bot=self.tt_bot,
            session_factory=self.session_factory,
            app_config=self.app_config # Pass app_config
        )
        self.connections[server_key] = connection

        self.logger.info(f"Attempting to connect TeamTalkConnection for {server_key}...")
        if not await connection.connect(): # connect() now adds server to tt_bot and gets instance
            self.logger.error(f"Failed to initiate connection for {server_key} via TeamTalkConnection.connect().")
        else:
            self.logger.info(f"TeamTalkConnection for {server_key} initiated. Waiting for login events.")

    async def on_pytalk_my_login(self, server: PytalkServer):
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.logger.error(f"on_pytalk_my_login: Received login event for unknown instance: {tt_instance}. Server: {server.info.host}")
            return

        connection.login_complete_time = None # Reset this, will be set after channel join
        connection.mark_finalized(False) # Mark as not finalized until channel join and cache tasks start

        server_name_display = "Unknown Server"
        try:
            server_props = tt_instance.server.get_properties()
            if server_props:
                server_name_display = pytalk.instance.sdk.ttstr(server_props.server_name)
        except Exception as e:
            self.logger.warning(f"[{connection.server_info.host}] Error getting server properties on login: {e}")

        self.logger.info(f"[{connection.server_info.host}] Successfully logged in to TeamTalk server: {server_name_display} (Host: {server.info.host}). Current instance: {connection.instance}")

        # Attempt to join the configured channel
        try:
            channel_id_or_path = self.app_config.CHANNEL # From main app_config for this connection
            channel_password = self.app_config.CHANNEL_PASSWORD or ""
            target_channel_name_log = channel_id_or_path

            final_channel_id = -1

            if channel_id_or_path.isdigit():
                final_channel_id = int(channel_id_or_path)
                # Optionally, resolve and log channel name if ID is given
                chan_obj_log = tt_instance.get_channel(final_channel_id)
                if chan_obj_log:
                    target_channel_name_log = pytalk.instance.sdk.ttstr(chan_obj_log.name)
            else: # Path based channel
                channel_obj = tt_instance.get_channel_from_path(channel_id_or_path)
                if channel_obj:
                    final_channel_id = channel_obj.id
                    target_channel_name_log = pytalk.instance.sdk.ttstr(channel_obj.name)
                else:
                    self.logger.error(f"[{connection.server_info.host}] Channel path '{channel_id_or_path}' not found during login.")

            if final_channel_id != -1:
                self.logger.info(f"[{connection.server_info.host}] Attempting to join channel: '{target_channel_name_log}' (Resolved ID: {final_channel_id}).")
                # join_channel_by_id is synchronous in pytalk
                tt_instance.join_channel_by_id(final_channel_id, password=channel_password)
                # Successful join will trigger on_pytalk_user_join for the bot itself,
                # which will then call _finalize_bot_login_sequence for this connection.
            else:
                self.logger.warning(f"[{connection.server_info.host}] Could not resolve channel '{channel_id_or_path}'. Bot remains in default channel. Finalization may occur if already in target.")
                # If bot is already in the target channel (e.g. default channel is target), on_user_join might not fire for bot.
                # We might need to check current channel and finalize if it matches.
                current_bot_channel_id = tt_instance.getMyCurrentChannelID()
                if current_bot_channel_id == final_channel_id or (final_channel_id == -1 and current_bot_channel_id is not None): # or if no specific channel was required and bot is in some channel
                     self.logger.info(f"[{connection.server_info.host}] Bot already in a channel or no specific channel join needed. Attempting to finalize.")
                     current_channel_obj = tt_instance.get_channel(current_bot_channel_id)
                     if current_channel_obj:
                        await self._finalize_bot_login_sequence(connection, current_channel_obj)
                     else:
                        self.logger.error(f"[{connection.server_info.host}] Bot in channel ID {current_bot_channel_id}, but channel object not found.")

        except PytalkPermissionError as e_perm_join:
            self.logger.error(f"[{connection.server_info.host}] Pytalk PermissionError joining channel '{target_channel_name_log}': {e_perm_join}.", exc_info=True)
        except ValueError as e_val_join: # E.g. invalid path/ID
            self.logger.error(f"[{connection.server_info.host}] ValueError joining channel '{target_channel_name_log}': {e_val_join}.", exc_info=True)
        except TimeoutError as e_timeout_join:
            self.logger.error(f"[{connection.server_info.host}] TimeoutError during channel operations for '{target_channel_name_log}': {e_timeout_join}.", exc_info=True)
            await self._initiate_reconnect_for_connection(connection)
        except TeamTalkException as e_pytalk_join:
            self.logger.error(f"[{connection.server_info.host}] Pytalk specific error joining channel '{target_channel_name_log}': {e_pytalk_join}.", exc_info=True)
            await self._initiate_reconnect_for_connection(connection)
        except Exception as e:
            self.logger.error(f"[{connection.server_info.host}] Unexpected error during channel join logic: {e}", exc_info=True)
            await self._initiate_reconnect_for_connection(connection)


    async def _finalize_bot_login_sequence(self, connection: TeamTalkConnection, channel: PytalkChannel):
        """Handles the final steps of a specific connection's login and initialization sequence."""
        if connection.is_finalized:
            self.logger.info(f"[{connection.server_info.host}] Login sequence already finalized. Skipping.")
            return

        if not connection.instance:
            self.logger.error(f"[{connection.server_info.host}] Cannot finalize login sequence: instance not available in connection object.")
            return

        tt_instance = connection.instance
        channel_name_display = pytalk.instance.sdk.ttstr(channel.name) if hasattr(channel, "name") and isinstance(channel.name, bytes) else str(channel.name)
        self.logger.info(f"[{connection.server_info.host}] Bot successfully joined channel: {channel_name_display}. Finalizing login sequence...")

        # Initial population of online users cache for this connection
        self.logger.info(f"[{connection.server_info.host}] Performing initial population of online users cache...")
        try:
            initial_online_users = tt_instance.server.get_users()
            connection.online_users_cache.clear()
            for u in initial_online_users:
                if hasattr(u, "id"):
                    connection.online_users_cache[u.id] = u
            self.logger.info(f"[{connection.server_info.host}] Online users cache initialized with {len(connection.online_users_cache)} users.")
        except Exception as e:
            self.logger.error(f"[{connection.server_info.host}] Error during initial online users cache population: {e}", exc_info=True)

        # Start background tasks (periodic sync, populate accounts) for this connection
        connection.start_background_tasks()

        try:
            # Use PytalkStatus helper for status
            gender = self.app_config.GENDER.lower()
            base_status = PytalkStatus.online # Default to online

            status_val = PytalkStatus.online.neutral # Default
            if gender == "male": status_val = PytalkStatus.online.male
            elif gender == "female": status_val = PytalkStatus.online.female

            tt_instance.change_status(status_val, self.app_config.STATUS_TEXT)
            connection.login_complete_time = datetime.utcnow()
            connection.mark_finalized(True) # Mark as finalized
            self.logger.debug(f"[{connection.server_info.host}] TeamTalk status set to: '{self.app_config.STATUS_TEXT}'.")
            self.logger.info(f"[{connection.server_info.host}] TeamTalk login sequence finalized at {connection.login_complete_time}.")
        except Exception as e:
            self.logger.error(f"[{connection.server_info.host}] Error setting status or login_complete_time for bot: {e}", exc_info=True)

    async def on_pytalk_user_join(self, user: PytalkUser, channel: PytalkChannel):
        tt_instance = getattr(user.server, "teamtalk_instance", None) or getattr(user, "teamtalk_instance", None)
        if not tt_instance:
            self.logger.error(f"CRITICAL: Could not retrieve TeamTalk instance in on_pytalk_user_join for user {pytalk.instance.sdk.ttstr(user.username)}. Cannot process event.")
            return

        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.logger.error(f"on_pytalk_user_join: Received event for instance not managed: {tt_instance}")
            return

        connection.update_caches_on_event("user_join", user)

        my_user_id = tt_instance.getMyUserID()
        if my_user_id is None:
            self.logger.error(f"[{connection.server_info.host}] CRITICAL: Failed to get bot's own user ID in on_user_join.")
            return

        if user.id == my_user_id:
            # This is the bot itself joining the channel, finalize its setup for this connection
            if not connection.is_finalized:
                await self._finalize_bot_login_sequence(connection, channel)
            else:
                self.logger.info(f"[{connection.server_info.host}] Bot re-joined channel {pytalk.instance.sdk.ttstr(channel.name)}, already finalized.")
        else:
            # This is another user joining a channel
            # The send_join_leave_notification_logic needs to be called with the correct connection context
            await send_join_leave_notification_logic(
                NOTIFICATION_EVENT_JOIN, user, connection.instance, connection.login_complete_time, self.tg_bot_event, self.session_factory, self.user_settings_cache
            )

    async def on_pytalk_my_connection_lost(self, server: PytalkServer):
        # server object here is PytalkServer, its server.teamtalk_instance is the one that got lost
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.logger.error(f"on_pytalk_my_connection_lost: Received event for unknown instance: {tt_instance}. Server host from event: {server.info.host if server and server.info else 'Unknown'}")
            # Try to find by server_info if instance lookup failed (e.g. instance object changed)
            if server and server.info:
                 connection = self._get_connection_by_server_info(server.info)
                 if not connection:
                     self.logger.error(f"Still could not find connection for lost server {server.info.host}:{server.info.tcp_port}")
                     return # Cannot proceed without a connection object
                 else:
                     self.logger.warning(f"Found connection for {server.info.host} via server_info after instance lookup failed for connection_lost.")
            else:
                return


        server_host_display = connection.server_info.host if connection else 'Unknown Server'
        self.logger.warning(f"[{server_host_display}] Connection lost to server. Initiating reconnection process...")

        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks() # Stop tasks for this connection

        # Initiate reconnect for this specific connection
        await self._initiate_reconnect_for_connection(connection)

    async def _initiate_reconnect_for_connection(self, connection: TeamTalkConnection):
        """Attempts to reconnect a specific TeamTalkConnection."""
        if not connection:
            self.logger.error("Reconnect requested for a null connection object.")
            return

        server_key = f"{connection.server_info.host}:{connection.server_info.tcp_port}"
        self.logger.info(f"[{server_key}] Starting reconnection logic.")

        # Simple retry loop for now, could use exponential backoff later
        # This should not block other operations of the Application.
        # It might be better to schedule this as a separate task if it involves long waits.
        # For now, direct await for simplicity in the event handler flow.

        # Ensure old instance is cleaned up from pytalk_bot.teamtalks if necessary
        # Pytalk itself might handle this, or we might need to remove and re-add.
        # Current pytalk_bot.add_server appends. If an old instance for same server exists and is problematic,
        # it should be handled. For now, we assume pytalk_bot handles replacing/managing its internal list,
        # or that a new `connect()` call on TeamTalkConnection will manage it.
        # The `connection.connect()` itself calls `pytalk_bot.add_server`.

        await connection.disconnect_instance() # Ensure clean state before reconnect

        self.logger.info(f"[{server_key}] Attempting to re-establish connection...")
        if await connection.connect():
            self.logger.info(f"[{server_key}] Reconnect attempt initiated (add_server called). Waiting for login events.")
            # Login and channel join will be handled by on_pytalk_my_login and on_pytalk_user_join
        else:
            self.logger.error(f"[{server_key}] Failed to re-initiate connection via connection.connect(). Will rely on next on_ready or manual trigger.")
            # Consider scheduling a delayed retry here if connect() fails immediately
            # For now, this means it won't auto-retry if the add_server step fails.
            # A more robust solution would involve a retry loop for connection.connect() itself.
            # This is simplified from the original global `initiate_reconnect_task`.
            # A proper replacement for `initiate_reconnect_task` would be a persistent task per connection.

    async def on_pytalk_my_kicked_from_channel(self, channel_obj: PytalkChannel):
        tt_instance = channel_obj.teamtalk
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.logger.error(f"on_pytalk_my_kicked_from_channel: Received event for unknown instance: {tt_instance}")
            return

        channel_name = pytalk.instance.sdk.ttstr(channel_obj.name) if channel_obj and channel_obj.name else "Unknown Channel"
        self.logger.warning(f"[{connection.server_info.host}] Kicked from channel '{channel_name}'. Initiating full reconnection for this connection...")

        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks()
        await self._initiate_reconnect_for_connection(connection) # Reconnect this specific connection

    async def on_pytalk_message(self, message: TeamTalkMessage):
        tt_instance = message.teamtalk_instance # All message types should have this
        connection = self._get_connection_by_instance(tt_instance)

        if not connection or not connection.instance:
            self.logger.error(f"on_pytalk_message: Received message for unknown or uninitialized instance. Message from: {message.from_id}")
            return

        # Ignore messages from self or not private
        if (message.from_id == connection.instance.getMyUserID() or
                message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE):
            return

        sender_username = pytalk.instance.sdk.ttstr(message.user.username)
        message_content = message.content.strip()
        self.logger.debug(f"[{connection.server_info.host}] Received private TT message from {sender_username}: '{message_content[:100]}...'.")

        # Determine reply language (e.g., admin's preferred language)
        # This part needs access to user_settings_cache, which is self.user_settings_cache
        bot_reply_language_code = DEFAULT_LANGUAGE_CODE
        if self.app_config.TG_ADMIN_CHAT_ID:
            admin_settings = self.user_settings_cache.get(self.app_config.TG_ADMIN_CHAT_ID)
            if admin_settings and admin_settings.language_code:
                bot_reply_language_code = admin_settings.language_code

        translator = get_translator(bot_reply_language_code)
        _ = translator.gettext # For handlers that expect _

        command_parts = message_content.split(maxsplit=1)
        command_name = command_parts[0].lower()

        # Adapted TT_COMMAND_HANDLERS logic
        tt_command_handlers = {
            "/sub": handle_tt_subscribe_command,
            "/unsub": handle_tt_unsubscribe_command,
            "/add_admin": handle_tt_add_admin_command,
            "/remove_admin": handle_tt_remove_admin_command,
            "/help": handle_tt_help_command,
        }
        handler = tt_command_handlers.get(command_name)

        async with self.session_factory() as session:
            if handler:
                # Adapt handler calls to pass necessary context like connection, app, session, _
                # This is a significant change for these handlers.
                # For now, let's assume they will be refactored to accept `app` or `connection`.
                # Example: await handler(message, app=self, connection=connection, session=session, translator=translator)
                # The original handlers took specific arguments. We need to map them.
                args_str = command_parts[1] if len(command_parts) > 1 else None
                if command_name in ["/add_admin", "/remove_admin"]:
                    await handler(message, args_str=args_str, session=session, translator=translator, app=self, connection=connection)
                elif command_name == "/help":
                    await handler(message, _=_, app=self, connection=connection) # Original took message, _
                else: # /sub, /unsub
                    await handler(message, session=session, _=_, app=self, connection=connection)
            elif message_content.startswith("/"):
                await handle_tt_unknown_command(message, _, connection=connection) # Pass connection
            else:
                # forward_tt_message_to_telegram_admin needs tg_bot and admin_chat_id from app_config
                await forward_tt_message_to_telegram_admin(message, self.tg_bot_event, self.app_config, connection.server_info.host)


    async def on_pytalk_user_login(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection: return
        connection.update_caches_on_event("user_login", user)
        # Notification logic
        await send_join_leave_notification_logic(
            event_type=NOTIFICATION_EVENT_JOIN,
            user=user,
            tt_instance=connection.instance,
            login_complete_time=connection.login_complete_time,
            bot=self.tg_bot_event,
            session_factory=self.session_factory,
            user_settings_cache=self.user_settings_cache,
            subscribed_users_cache=self.subscribed_users_cache,
            online_users_cache_for_instance=connection.online_users_cache,
            app_config_instance=self.app_config
        )

    async def on_pytalk_user_logout(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection: return
        connection.update_caches_on_event("user_logout", user)
        # Notification logic
        await send_join_leave_notification_logic(
            event_type=NOTIFICATION_EVENT_LEAVE,
            user=user,
            tt_instance=connection.instance,
            login_complete_time=connection.login_complete_time,
            bot=self.tg_bot_event,
            session_factory=self.session_factory,
            user_settings_cache=self.user_settings_cache,
            subscribed_users_cache=self.subscribed_users_cache,
            online_users_cache_for_instance=connection.online_users_cache,
            app_config_instance=self.app_config
        )

    async def on_pytalk_user_update(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection: return
        connection.update_caches_on_event("user_update", user)

    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount):
        # UserAccount events might not directly provide the teamtalk_instance.
        # We might need to assume it's for all connections or find a way to associate.
        # For now, update all connections. This is a simplification.
        # A better approach: if pytalk.UserAccount has a reference to its server/instance.
        # Assuming account object might have `account.teamtalk_instance` or similar if library supports it.
        # If not, this event applies globally or needs routing if different servers have different accounts.
        # The provided pytalk docs don't show teamtalk_instance on UserAccount events.
        # For now, iterate and update all, or pick a "primary" if that concept exists.
        # Let's assume for now these events are instance-specific if `account.teamtalk_instance` is available.
        # If `account.teamtalk_instance` is NOT available, these caches might need to be global in App,
        # or we only handle them for a "primary" connection.
        # The problem states `user_accounts_cache` is per-connection. So the event *must* be attributable.
        # Checking `pytalk/instance.py` for `CLIENTEVENT_CMD_USERACCOUNT_NEW` dispatch.
        # It dispatches `TeamTalkUserAccount(self, msg.useraccount)`. `TeamTalkUserAccount` constructor takes `teamtalk_instance`.
        # So, `account.teamtalk_instance` SHOULD be available.

        tt_instance = getattr(account, 'teamtalk_instance', None)
        if not tt_instance:
             self.logger.warning(f"on_pytalk_user_account_new: No teamtalk_instance found on account object. Cannot route event. Account: {account.username}")
             # Fallback: update all connections if no instance info
             for conn_key, conn_val in self.connections.items():
                 conn_val.update_caches_on_event("user_account_new", account)
             return

        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.logger.error(f"on_pytalk_user_account_new: Received event for instance not managed: {tt_instance}")
            return
        connection.update_caches_on_event("user_account_new", account)

    async def on_pytalk_user_account_remove(self, account: pytalk.UserAccount):
        tt_instance = getattr(account, 'teamtalk_instance', None)
        if not tt_instance:
             self.logger.warning(f"on_pytalk_user_account_remove: No teamtalk_instance found on account object. Cannot route event. Account: {account.username}")
             for conn_key, conn_val in self.connections.items():
                 conn_val.update_caches_on_event("user_account_remove", account)
             return

        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.logger.error(f"on_pytalk_user_account_remove: Received event for instance not managed: {tt_instance}")
            return
        connection.update_caches_on_event("user_account_remove", account)

    # --- Application Lifecycle Methods ---
    async def _on_startup_logic(self, bot: Bot, dispatcher: Dispatcher): # bot and dispatcher are TG bot/dp
        """Internal logic for startup, similar to old on_startup."""
        self.logger.info("Application startup: Initializing TeamTalk components...")

        # Start the main Pytalk event processing loop
        # self.tt_bot._async_setup_hook() should be called by pytalk itself if needed
        # The old code did: teamtalk_task = asyncio.create_task(tt_bot_module.tt_bot._start(), name="teamtalk_bot_task_dispatcher")
        # self.tt_bot.run() is blocking. self.tt_bot._start() is the async version.
        if self.teamtalk_task is None or self.teamtalk_task.done():
            await self.tt_bot._async_setup_hook() # Ensure tt_bot has loop
            self.teamtalk_task = asyncio.create_task(self.tt_bot._start(), name="teamtalk_bot_task_dispatcher")
            self.logger.info("Pytalk main event loop task started.")
        else:
            self.logger.info("Pytalk main event loop task already running.")

        # Load global caches (admin_ids, subscribed_users)
        async with self.session_factory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
            self.admin_ids_cache.update(db_admin_ids)

            db_subscriber_ids = await crud.get_all_subscribers_ids(session)
            self.subscribed_users_cache.update(db_subscriber_ids)
        self.logger.info(f"Admin IDs cache populated with {len(self.admin_ids_cache)} IDs.")
        self.logger.info(f"Subscribed users cache populated with {len(self.subscribed_users_cache)} IDs.")

        await self.load_user_settings_to_app_cache() # Use app's method
        # self.logger.info("User settings cache populated.") # Logging is inside the method

        # Add configured admin from TG_ADMIN_CHAT_ID
        tg_admin_chat_id = self.app_config.TG_ADMIN_CHAT_ID
        if tg_admin_chat_id is not None:
            async with self.session_factory() as session:
                await crud.add_admin(session, tg_admin_chat_id) # Ensures admin is in DB
                self.admin_ids_cache.add(tg_admin_chat_id) # Also add to cache
            self.logger.info(f"Ensured TG_ADMIN_CHAT_ID {tg_admin_chat_id} is admin.")

        # Set Telegram commands
        # await set_telegram_commands(self.tg_bot_event, admin_ids=list(self.admin_ids_cache), default_language_code=self.app_config.DEFAULT_LANG)
        # Pass app and session to set_telegram_commands
        async with self.session_factory() as session: # Create a session for set_telegram_commands
            await set_telegram_commands(
                bot=self.tg_bot_event,
                admin_ids=list(self.admin_ids_cache),
                default_language_code=self.app_config.DEFAULT_LANG,
                app=self, # Pass self (the Application instance)
                session=session # Pass the created session
            )
        self.logger.info("Telegram bot commands set.")

        # The on_pytalk_ready event will handle connecting to TeamTalk servers.
        # It's triggered by tt_bot._start() eventually.

    async def _on_shutdown_logic(self, dispatcher: Dispatcher):
        """Internal logic for shutdown, similar to old on_shutdown."""
        self.logger.warning('Application shutting down...')

        # Cancel Pytalk main event loop task
        if self.teamtalk_task and not self.teamtalk_task.done():
            self.logger.info("Cancelling Pytalk main event loop task...")
            self.teamtalk_task.cancel()
            try:
                await self.teamtalk_task
            except asyncio.CancelledError:
                self.logger.info("Pytalk main event loop task cancelled successfully.")
            except Exception as e:
                self.logger.error(f"Error awaiting cancelled Pytalk task: {e}", exc_info=True)
        elif self.teamtalk_task:
            self.logger.info("Pytalk main event loop task was already done.")
        else:
            self.logger.info("No Pytalk main event loop task found to cancel.")

        # Disconnect all TeamTalkConnection instances
        self.logger.info("Disconnecting TeamTalk instances...")
        for conn_key, connection in self.connections.items():
            self.logger.info(f"Shutting down connection for {conn_key}...")
            await connection.disconnect_instance() # This handles logout, disconnect, task cleanup
        self.logger.info("All TeamTalk connections processed for shutdown.")

        # Pytalk's own cleanup (closing sockets etc.) should be handled by tt_bot when its loop ends
        # or if it has an explicit close/cleanup method.
        # The old code iterated tt_bot_module.tt_bot.teamtalks and called shutdown_tt_instance.
        # Our connection.disconnect_instance() covers the instance-specific parts.
        # We might need a self.tt_bot.close() or similar if pytalk lib requires it.
        # For now, assume cancelling _start() is enough for pytalk's bot object.


        # Close Telegram bot sessions
        if hasattr(self.tg_bot_event, 'session') and self.tg_bot_event.session:
            await self.tg_bot_event.session.close()
        if self.tg_bot_message and hasattr(self.tg_bot_message, 'session') and self.tg_bot_message.session and self.tg_bot_message is not self.tg_bot_event:
            await self.tg_bot_message.session.close()
        self.logger.info("Telegram bot sessions closed.")
        self.logger.info("Application shutdown sequence complete.")

    async def _global_error_handler(self, event: ErrorEvent, bot: Bot): # bot is tg_bot_event
        """Global error handler for uncaught exceptions in Aiogram handlers."""
        escaped_exception_text = html.quote(str(event.exception))
        self.logger.critical(f"Unhandled exception in Aiogram handler: {event.exception}", exc_info=True)

        if self.app_config.TG_ADMIN_CHAT_ID:
            try:
                admin_critical_translator = get_translator('ru') # Assuming admin lang is ru for this
                critical_error_header = admin_critical_translator.gettext("<b>Critical error!</b>")
                error_text = (
                    f"{critical_error_header}\n"
                    f"<b>Тип ошибки:</b> {type(event.exception).__name__}\n"
                    f"<b>Сообщение:</b> {escaped_exception_text}"
                )
                await self.tg_bot_event.send_message(self.app_config.TG_ADMIN_CHAT_ID, error_text, parse_mode="HTML")
            except Exception as e:
                self.logger.error(f"Error sending critical error message to admin chat: {e}", exc_info=True)

        update = event.update
        user_id = None
        if update.message and update.message.from_user: user_id = update.message.from_user.id
        elif update.callback_query and update.callback_query.from_user: user_id = update.callback_query.from_user.id

        lang_code = DEFAULT_LANGUAGE_CODE
        if user_id:
            user_settings = self.user_settings_cache.get(user_id) # Access app's cache
            if user_settings and user_settings.language_code:
                lang_code = user_settings.language_code

        translator = get_translator(lang_code)
        user_message_key = "An unexpected error occurred. The administrator has been notified. Please try again later."
        user_message_text = translator.gettext(user_message_key)

        if not (user_id and self.app_config.TG_ADMIN_CHAT_ID and str(user_id) == str(self.app_config.TG_ADMIN_CHAT_ID)):
            try:
                if update.message:
                    await update.message.answer(user_message_text)
                elif update.callback_query and isinstance(update.callback_query.message, AiogramMessage):
                    await update.callback_query.message.answer(user_message_text)
                elif user_id: # Try direct send if no reply context
                     await self.tg_bot_event.send_message(chat_id=user_id, text=user_message_text)
            except Exception as e:
                self.logger.error(f"Error sending error message to user {user_id if user_id else 'Unknown'}: {e}", exc_info=True)


    async def run(self):
        """Sets up and runs the application."""
        self.logger.info("Application starting...")

        # Initialize Languages
        self.logger.info("Discovering available languages...")
        discovered_langs = discover_languages()
        AVAILABLE_LANGUAGES_DATA.clear() # Clear if populated by module-level import
        AVAILABLE_LANGUAGES_DATA.extend(discovered_langs)
        if not AVAILABLE_LANGUAGES_DATA:
            self.logger.critical("No languages discovered. Check locales setup.")
            return # Or raise
        else:
            self.logger.info(f"Available languages loaded: {[lang['code'] for lang in AVAILABLE_LANGUAGES_DATA]}")

        # Setup Aiogram Dispatcher
        # Order of middleware registration matters.
        # ApplicationMiddleware should be early, especially if others depend on `data["app"]`.
        self.dp.update.outer_middleware.register(ApplicationMiddleware(self)) # Inject app instance
        self.dp.update.outer_middleware.register(DbSessionMiddleware(self.session_factory))

        # Middlewares that depend on `data["app"]` or `data["session"]`
        self.dp.message.middleware(SubscriptionCheckMiddleware())
        self.dp.callback_query.middleware(SubscriptionCheckMiddleware())

        self.dp.message.middleware(UserSettingsMiddleware())
        self.dp.callback_query.middleware(UserSettingsMiddleware())

        # Middleware to provide a TeamTalkConnection
        # For now, no default_server_key, so it picks the first available connection.
        # This is suitable for the current single-server setup.
        self.dp.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
        self.dp.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))

        # CallbackAnswerMiddleware should be last among general purpose callback query middlewares
        self.dp.callback_query.middleware(CallbackAnswerMiddleware())

        # TeamTalkConnectionCheckMiddleware should be registered on specific routers/handlers
        # that require a fully active TT connection, not globally unless all handlers need it.
        # For now, I will register it globally for message and callback_query events
        # as most commands will likely interact with TeamTalk.
        # This can be refined later to be router-specific.
        self.dp.message.middleware(TeamTalkConnectionCheckMiddleware())
        self.dp.callback_query.middleware(TeamTalkConnectionCheckMiddleware())

        # Include Aiogram routers
        self.dp.include_router(user_commands_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(callback_router)
        self.dp.include_router(menu_callback_router)
        self.dp.include_router(subscriber_actions_router)
        self.dp.include_router(catch_all_router)

        # Register startup and shutdown handlers for Aiogram dispatcher
        self.dp.startup.register(self._on_startup_logic)
        self.dp.shutdown.register(self._on_shutdown_logic)
        self.dp.errors.register(self._global_error_handler)

        self.logger.info("Starting Telegram polling...")
        try:
            # Pass the event bot instance to start_polling
            await self.dp.start_polling(self.tg_bot_event, allowed_updates=self.dp.resolve_used_update_types(), app=self)
        finally:
            self.logger.info("Application finished.")


# === CONFIGURATION AND CLI BLOCK START ===
def main_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default=".env",
        help="Path to the configuration file (e.g., .env, prod.env). Defaults to '.env'",
    )
    args, _ = parser.parse_known_args()
    os.environ["APP_CONFIG_FILE_PATH"] = args.config

    # Now that env var is set, import app_config
    from bot.config import app_config as app_config_instance

    try:
        # uvloop installation attempt (optional)
        try:
            import uvloop
            uvloop.install()
            # Logger is not set up yet globally, print for now or log in app init
            print("uvloop installed and used.")
        except ImportError:
            print("uvloop not found, using default asyncio event loop.")

        app = Application(app_config_instance)
        asyncio.run(app.run())

    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by user.")
    except (ValueError, KeyError) as config_error:
        # This might catch errors from Pydantic model validation in app_config_instance
        print(f"CRITICAL: Configuration Error: {config_error}. Please check your .env file or environment variables.")
        traceback.print_exc()
    except Exception as e:
        print(f"CRITICAL: An unexpected critical error occurred at CLI level: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main_cli()
