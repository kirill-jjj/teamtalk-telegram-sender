import asyncio
import os
import argparse
import traceback # For detailed error reporting before logger is set up
import logging # Added for Application class
from datetime import datetime # Added for Application class Pytalk event handlers

# Standard library imports for Application class
from typing import Dict, Optional, Any

# SQLAlchemy / SQLModel imports
from sqlmodel.ext.asyncio.session import AsyncSession
from bot.models import UserSettings
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlalchemy.orm import selectinload


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
from bot.logging_setup import setup_logging
# from bot.config import app_config # Config imported in main_cli

from bot.database.engine import SessionFactory
from bot.database import crud

from bot.core.languages import discover_languages, AVAILABLE_LANGUAGES_DATA, DEFAULT_LANGUAGE_CODE
from bot.language import get_translator

# Telegram specific components to be managed by Application
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message
from bot.telegram_bot.commands import set_telegram_commands
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    SubscriptionCheckMiddleware,
    ApplicationMiddleware,
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware
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
from bot.teamtalk_bot.utils import (
    forward_tt_message_to_telegram_admin,
)
from bot.teamtalk_bot.commands import (
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
    TT_CACHE_SYNC_RETRY_DELAY_SECONDS,
)
from bot.core.notifications import send_join_leave_notification_logic


logger = logging.getLogger(__name__)

class Application:
    def __init__(self, app_config_instance):
        self.app_config = app_config_instance
        self.logger = setup_logging()

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
        self.user_settings_cache: Dict[int, Any] = {}

        self.teamtalk_task: Optional[asyncio.Task] = None
        self._register_pytalk_event_handlers()

    async def load_user_settings_to_app_cache(self):
        """Loads all user settings from DB into the application's cache."""
        async with self.session_factory() as session:
            stmt = select(UserSettings)
            result = await session.exec(stmt)
            all_settings = result.all()
            for setting in all_settings:
                self.user_settings_cache[setting.telegram_id] = setting
            self.logger.info(f"Loaded {len(self.user_settings_cache)} user settings into app cache.")

    async def get_or_create_user_settings(self, telegram_id: int, session: AsyncSession) -> UserSettings:
        """Gets user settings from app cache or DB, creates if not exists."""
        cached_settings = self.user_settings_cache.get(telegram_id)
        if cached_settings:
            return cached_settings

        # If not in cache, try DB
        user_settings = await session.get(
            UserSettings,
            telegram_id,
            options=[selectinload(UserSettings.muted_users_list)]
        )
        if not user_settings:
            self.logger.info(f"No settings found for user {telegram_id}, creating new ones.")
            user_settings = UserSettings(
                telegram_id=telegram_id,
                language_code=self.app_config.DEFAULT_LANG
            )
            session.add(user_settings)
            try:
                await session.commit()
                await session.refresh(user_settings)
                self.logger.info(f"Successfully created and saved new settings for user {telegram_id}.")
            except SQLAlchemyError as e:
                await session.rollback()
                self.logger.error(f"Database error creating settings for user {telegram_id}: {e}", exc_info=True)
                # Return a default non-persistent object on error.
                return UserSettings(telegram_id=telegram_id, language_code=self.app_config.DEFAULT_LANG)

        self.user_settings_cache[telegram_id] = user_settings
        return user_settings

    def _get_connection_by_instance(self, tt_instance: pytalk.instance.TeamTalkInstance) -> Optional[TeamTalkConnection]:
        for conn in self.connections.values():
            if conn.instance is tt_instance:
                return conn
        self.logger.warning(f"Could not find an active TeamTalkConnection for instance: {tt_instance}")
        return None

    def _get_connection_by_server_info(self, server_info: pytalk.TeamTalkServerInfo) -> Optional[TeamTalkConnection]:
        # Assuming server_info.host and server_info.tcp_port can uniquely identify a connection
        server_key = f"{server_info.host}:{server_info.tcp_port}"
        return self.connections.get(server_key)

    def _register_pytalk_event_handlers(self):
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

    # --- Pytalk Event Handlers ---
    async def on_pytalk_ready(self):
        """
        Called when self.tt_bot.run() is effectively started.
        Initiates connections to configured TeamTalk servers.
        """
        self.logger.info("Pytalk Bot is ready. Initializing TeamTalk connections...")
        # Assuming a single server configuration from app_config for now.
        server_config = self.app_config
        pytalk_server_info = pytalk.TeamTalkServerInfo(
            host=server_config.HOSTNAME,
            tcp_port=server_config.PORT,
            udp_port=server_config.PORT,
            username=server_config.USERNAME,
            password=server_config.PASSWORD,
            encrypted=server_config.ENCRYPTED,
            nickname=server_config.NICKNAME,
            join_channel_id=int(server_config.CHANNEL) if server_config.CHANNEL.isdigit() else -1,
            join_channel_password=server_config.CHANNEL_PASSWORD or ""
        )

        server_key = f"{pytalk_server_info.host}:{pytalk_server_info.tcp_port}"

        if server_key in self.connections:
            self.logger.warning(f"Connection for {server_key} already exists. Reconnecting.")
            await self.connections[server_key].disconnect_instance()

        connection = TeamTalkConnection(
            server_info=pytalk_server_info,
            pytalk_bot=self.tt_bot,
            session_factory=self.session_factory,
            app_config=self.app_config
        )
        self.connections[server_key] = connection

        self.logger.info(f"Attempting to connect TeamTalkConnection for {server_key}...")
        if not await connection.connect():
            self.logger.error(f"Failed to initiate connection for {server_key} via TeamTalkConnection.connect().")
        else:
            self.logger.info(f"TeamTalkConnection for {server_key} initiated. Waiting for login events.")

    async def on_pytalk_my_login(self, server: PytalkServer):
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.logger.error(f"on_pytalk_my_login: Received login event for unknown instance: {tt_instance}. Server: {server.info.host}")
            return

        connection.login_complete_time = None
        connection.mark_finalized(False)

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
            channel_id_or_path = self.app_config.CHANNEL
            channel_password = self.app_config.CHANNEL_PASSWORD or ""
            target_channel_name_log = channel_id_or_path

            final_channel_id = -1

            if channel_id_or_path.isdigit():
                final_channel_id = int(channel_id_or_path)
                chan_obj_log = tt_instance.get_channel(final_channel_id)
                if chan_obj_log:
                    target_channel_name_log = pytalk.instance.sdk.ttstr(chan_obj_log.name)
            else:
                channel_obj = tt_instance.get_channel_from_path(channel_id_or_path)
                if channel_obj:
                    final_channel_id = channel_obj.id
                    target_channel_name_log = pytalk.instance.sdk.ttstr(channel_obj.name)
                else:
                    self.logger.error(f"[{connection.server_info.host}] Channel path '{channel_id_or_path}' not found during login.")

            if final_channel_id != -1:
                self.logger.info(f"[{connection.server_info.host}] Attempting to join channel: '{target_channel_name_log}' (Resolved ID: {final_channel_id}).")
                tt_instance.join_channel_by_id(final_channel_id, password=channel_password)
            else:
                self.logger.warning(f"[{connection.server_info.host}] Could not resolve channel '{channel_id_or_path}'. Bot remains in default channel.")
                current_bot_channel_id = tt_instance.getMyCurrentChannelID()
                if current_bot_channel_id == final_channel_id or (final_channel_id == -1 and current_bot_channel_id is not None):
                     self.logger.info(f"[{connection.server_info.host}] Bot already in a channel or no specific channel join needed. Attempting to finalize.")
                     current_channel_obj = tt_instance.get_channel(current_bot_channel_id)
                     if current_channel_obj:
                        await self._finalize_bot_login_sequence(connection, current_channel_obj)
                     else:
                        self.logger.error(f"[{connection.server_info.host}] Bot in channel ID {current_bot_channel_id}, but channel object not found.")

        except PytalkPermissionError as e_perm_join:
            self.logger.error(f"[{connection.server_info.host}] Pytalk PermissionError joining channel '{target_channel_name_log}': {e_perm_join}.", exc_info=True)
        except ValueError as e_val_join:
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

        connection.start_background_tasks()

        try:
            gender = self.app_config.GENDER.lower()
            status_val = PytalkStatus.online.neutral
            if gender == "male": status_val = PytalkStatus.online.male
            elif gender == "female": status_val = PytalkStatus.online.female

            tt_instance.change_status(status_val, self.app_config.STATUS_TEXT)
            connection.login_complete_time = datetime.utcnow()
            connection.mark_finalized(True)
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
            if not connection.is_finalized:
                await self._finalize_bot_login_sequence(connection, channel)
            else:
                self.logger.info(f"[{connection.server_info.host}] Bot re-joined channel {pytalk.instance.sdk.ttstr(channel.name)}, already finalized.")
        else:
            # Notification for other users joining a channel is handled by on_pytalk_user_login.
            pass

    async def on_pytalk_my_connection_lost(self, server: PytalkServer):
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.logger.error(f"on_pytalk_my_connection_lost: Received event for unknown instance: {tt_instance}. Server host from event: {server.info.host if server and server.info else 'Unknown'}")
            if server and server.info:
                 connection = self._get_connection_by_server_info(server.info)
                 if not connection:
                     self.logger.error(f"Still could not find connection for lost server {server.info.host}:{server.info.tcp_port}")
                     return
                 else:
                     self.logger.warning(f"Found connection for {server.info.host} via server_info after instance lookup failed for connection_lost.")
            else:
                return


        server_host_display = connection.server_info.host if connection else 'Unknown Server'
        self.logger.warning(f"[{server_host_display}] Connection lost to server. Initiating reconnection process...")

        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks()

        await self._initiate_reconnect_for_connection(connection)

    async def _initiate_reconnect_for_connection(self, connection: TeamTalkConnection):
        """Attempts to reconnect a specific TeamTalkConnection."""
        if not connection:
            self.logger.error("Reconnect requested for a null connection object.")
            return

        server_key = f"{connection.server_info.host}:{connection.server_info.tcp_port}"
        self.logger.info(f"[{server_key}] Starting reconnection logic.")

        await connection.disconnect_instance()

        self.logger.info(f"[{server_key}] Attempting to re-establish connection...")
        if await connection.connect():
            self.logger.info(f"[{server_key}] Reconnect attempt initiated. Waiting for login events.")
        else:
            self.logger.error(f"[{server_key}] Failed to re-initiate connection via connection.connect().")

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
        await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_message(self, message: TeamTalkMessage):
        tt_instance = message.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection or not connection.instance:
            self.logger.error(f"on_pytalk_message: Received message for unknown or uninitialized instance. Message from: {message.from_id}")
            return

        if (message.from_id == connection.instance.getMyUserID() or
                message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE):
            return

        sender_username = pytalk.instance.sdk.ttstr(message.user.username)
        message_content = message.content.strip()
        self.logger.debug(f"[{connection.server_info.host}] Received private TT message from {sender_username}: '{message_content[:100]}...'.")

        bot_reply_language_code = DEFAULT_LANGUAGE_CODE
        if self.app_config.TG_ADMIN_CHAT_ID:
            admin_settings = self.user_settings_cache.get(self.app_config.TG_ADMIN_CHAT_ID)
            if admin_settings and admin_settings.language_code:
                bot_reply_language_code = admin_settings.language_code

        translator = get_translator(bot_reply_language_code)
        _ = translator.gettext

        command_parts = message_content.split(maxsplit=1)
        command_name = command_parts[0].lower()

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
                args_str = command_parts[1] if len(command_parts) > 1 else None
                if command_name in ["/add_admin", "/remove_admin"]:
                    await handler(message, args_str=args_str, session=session, translator=translator, app=self, connection=connection)
                elif command_name == "/help":
                    await handler(message, _=_, app=self, connection=connection)
                else:
                    await handler(message, session=session, _=_, app=self, connection=connection)
            elif message_content.startswith("/"):
                await handle_tt_unknown_command(message, _, connection=connection)
            else:
                await forward_tt_message_to_telegram_admin(
                    message=message,
                    app=self,
                    server_host_for_display=connection.server_info.host
                )


    async def on_pytalk_user_login(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection: return
        connection.update_caches_on_event("user_login", user)
        await send_join_leave_notification_logic(
            event_type=NOTIFICATION_EVENT_JOIN,
            tt_user=user,
            tt_instance=connection.instance,
            login_complete_time=connection.login_complete_time,
            bot=self.tg_bot_event,
            session_factory=self.session_factory,
            user_settings_cache=self.user_settings_cache,
            subscribed_users_cache=self.subscribed_users_cache,
            online_users_cache_for_instance=connection.online_users_cache,
            app_config_instance=self.app_config,
            app=self # PASS Application instance
        )

    async def on_pytalk_user_logout(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection: return
        connection.update_caches_on_event("user_logout", user)
        await send_join_leave_notification_logic(
            event_type=NOTIFICATION_EVENT_LEAVE,
            tt_user=user,
            tt_instance=connection.instance,
            login_complete_time=connection.login_complete_time,
            bot=self.tg_bot_event,
            session_factory=self.session_factory,
            user_settings_cache=self.user_settings_cache,
            subscribed_users_cache=self.subscribed_users_cache,
            online_users_cache_for_instance=connection.online_users_cache,
            app_config_instance=self.app_config,
            app=self
        )

    async def on_pytalk_user_update(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection: return
        connection.update_caches_on_event("user_update", user)

    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount):
        tt_instance = getattr(account, 'teamtalk_instance', None)
        if not tt_instance:
             self.logger.warning(f"on_pytalk_user_account_new: No teamtalk_instance found on account object. Cannot route event. Account: {account.username}")
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
    async def _on_startup_logic(self, bot: Bot, dispatcher: Dispatcher):
        """Internal logic for startup."""
        self.logger.info("Application startup: Initializing TeamTalk components...")

        if self.teamtalk_task is None or self.teamtalk_task.done():
            await self.tt_bot._async_setup_hook()
            self.teamtalk_task = asyncio.create_task(self.tt_bot._start(), name="teamtalk_bot_task_dispatcher")
            self.logger.info("Pytalk main event loop task started.")
        else:
            self.logger.info("Pytalk main event loop task already running.")

        async with self.session_factory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
            self.admin_ids_cache.update(db_admin_ids)

            db_subscriber_ids = await crud.get_all_subscribers_ids(session)
            self.subscribed_users_cache.update(db_subscriber_ids)
        self.logger.info(f"Admin IDs cache populated with {len(self.admin_ids_cache)} IDs.")
        self.logger.info(f"Subscribed users cache populated with {len(self.subscribed_users_cache)} IDs.")

        await self.load_user_settings_to_app_cache()

        tg_admin_chat_id = self.app_config.TG_ADMIN_CHAT_ID
        if tg_admin_chat_id is not None:
            async with self.session_factory() as session:
                await crud.add_admin(session, tg_admin_chat_id)
                self.admin_ids_cache.add(tg_admin_chat_id)
            self.logger.info(f"Ensured TG_ADMIN_CHAT_ID {tg_admin_chat_id} is admin.")

        async with self.session_factory() as session:
            await set_telegram_commands(
                bot=self.tg_bot_event,
                admin_ids=list(self.admin_ids_cache),
                default_language_code=self.app_config.DEFAULT_LANG,
                app=self,
                session=session
            )
        self.logger.info("Telegram bot commands set.")


    async def _on_shutdown_logic(self, dispatcher: Dispatcher):
        """Internal logic for shutdown."""
        self.logger.warning('Application shutting down...')

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

        self.logger.info("Disconnecting TeamTalk instances...")
        for conn_key, connection in self.connections.items():
            self.logger.info(f"Shutting down connection for {conn_key}...")
            await connection.disconnect_instance()
        self.logger.info("All TeamTalk connections processed for shutdown.")


        if hasattr(self.tg_bot_event, 'session') and self.tg_bot_event.session:
            await self.tg_bot_event.session.close()
        if self.tg_bot_message and hasattr(self.tg_bot_message, 'session') and self.tg_bot_message.session and self.tg_bot_message is not self.tg_bot_event:
            await self.tg_bot_message.session.close()
        self.logger.info("Telegram bot sessions closed.")
        self.logger.info("Application shutdown sequence complete.")

    async def _global_error_handler(self, event: ErrorEvent, bot: Bot):
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
        self.dp.update.outer_middleware.register(ApplicationMiddleware(self))
        self.dp.update.outer_middleware.register(DbSessionMiddleware(self.session_factory))

        self.dp.message.middleware(SubscriptionCheckMiddleware())
        self.dp.callback_query.middleware(SubscriptionCheckMiddleware())

        self.dp.message.middleware(UserSettingsMiddleware())
        self.dp.callback_query.middleware(UserSettingsMiddleware())

        self.dp.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
        self.dp.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))

        self.dp.callback_query.middleware(CallbackAnswerMiddleware())

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
        try:
            import uvloop
            uvloop.install()
            print("uvloop installed and used.")
        except ImportError:
            print("uvloop not found, using default asyncio event loop.")

        app = Application(app_config_instance)
        asyncio.run(app.run())

    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by user.")
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}. Please check your .env file or environment variables.")
        traceback.print_exc()
    except Exception as e:
        print(f"CRITICAL: An unexpected critical error occurred at CLI level: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main_cli()
