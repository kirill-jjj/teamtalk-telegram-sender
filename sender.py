import asyncio
import enum
import logging
import os
import sys
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any

try:
    import uvloop
    uvloop.install()
    logging.info("Using uvloop.")
except ImportError:
    logging.info("uvloop not found, using standard asyncio loop.")

import pytalk
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import UserStatusMode
from pytalk.instance import TeamTalkInstance
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as TeamTalkUser
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, delete, select
from sqlalchemy import Enum as SQLAEnum
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ttstr = pytalk.instance.sdk.ttstr

class InfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno == logging.INFO

log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.addFilter(InfoFilter())

root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def load_config(env_path: str | None = None) -> dict[str, str]:
    load_dotenv(dotenv_path=env_path)
    config_data = {
        "TG_BOT_TOKEN": os.getenv("TG_BOT_TOKEN"),
        "TG_EVENT_TOKEN": os.getenv("TELEGRAM_BOT_EVENT_TOKEN") or os.getenv("TG_BOT_TOKEN"),
        "TG_BOT_MESSAGE_TOKEN": os.getenv("TG_BOT_MESSAGE_TOKEN"),
        "TG_ADMIN_CHAT_ID": os.getenv("TG_ADMIN_CHAT_ID"),
        "HOSTNAME": os.getenv("HOST_NAME"),
        "PORT": int(os.getenv("PORT", "9987")),
        "ENCRYPTED": os.getenv("ENCRYPTED") == "1",
        "USERNAME": os.getenv("USER_NAME"),
        "PASSWORD": os.getenv("PASSWORD"),
        "CHANNEL": os.getenv("CHANNEL"),
        "CHANNEL_PASSWORD": os.getenv("CHANNEL_PASSWORD"),
        "NICKNAME": os.getenv("NICK_NAME"),
        "STATUS_TEXT": os.getenv("STATUS_TEXT", ""),
        "CLIENT_NAME": os.getenv("CLIENT_NAME") or "TTTM",
        "SERVER_NAME": os.getenv("SERVER_NAME"),
        "ADMIN_USERNAME": os.getenv("ADMIN"),
        "GLOBAL_IGNORE_USERNAME": os.getenv("GLOBAL_IGNORE_USERNAME"),
        "DATABASE_FILE": os.getenv("DATABASE_FILE", "bot_data.db"),
    }
    if not config_data["TG_EVENT_TOKEN"] and not config_data["TG_BOT_TOKEN"]:
        raise ValueError("Missing required environment variable: TG_BOT_TOKEN or TELEGRAM_BOT_EVENT_TOKEN. Check .env file.")
    if not config_data["HOSTNAME"] or not config_data["USERNAME"] or not config_data["PASSWORD"] or not config_data["CHANNEL"] or not config_data["NICKNAME"]:
        raise ValueError("Missing other required environment variables. Check .env file.")
    return config_data

MIN_ARGS_FOR_ENV_PATH = 2
config = load_config(sys.argv[1] if len(sys.argv) >= MIN_ARGS_FOR_ENV_PATH else None)

tg_bot_event = Bot(token=config["TG_EVENT_TOKEN"])
tg_bot_message = Bot(token=config["TG_BOT_MESSAGE_TOKEN"]) if config["TG_BOT_MESSAGE_TOKEN"] else None

DATABASE_FILES = {"main": config["DATABASE_FILE"]}
async_engines = {db_name: create_async_engine(f"sqlite+aiosqlite:///{db_file}") for db_name, db_file in DATABASE_FILES.items()}
SessionFactory = sessionmaker(async_engines["main"], expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

async def init_db() -> None:
    async with async_engines["main"].begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")

class SubscribedUser(Base):
    __tablename__ = "subscribed_users"
    telegram_id = Column(Integer, primary_key=True, autoincrement=True)

class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(Integer, primary_key=True, autoincrement=True)

class Deeplink(Base):
    __tablename__ = "deeplinks"
    token = Column(String, primary_key=True)
    action = Column(String)
    payload = Column(String, nullable=True)
    expected_telegram_id = Column(Integer, nullable=True)
    expiry_time = Column(DateTime)

class NotificationSetting(enum.Enum):
    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"

class UserSettings(Base):
    __tablename__ = "user_settings"
    telegram_id = Column(Integer, primary_key=True)
    language = Column(String, default="en")
    notification_settings = Column(SQLAEnum(NotificationSetting), default=NotificationSetting.ALL)
    muted_users = Column(String, default="")
    mute_all = Column(Boolean, default=False)
    teamtalk_username = Column(String, nullable=True, index=True)
    not_on_online_enabled = Column(Boolean, default=False)
    not_on_online_confirmed = Column(Boolean, default=False)
    __table_args__ = (Index("ix_user_settings_telegram_id", "telegram_id"),)

USER_SETTINGS_CACHE: dict[int, dict[str, Any]] = {}
login_complete_time: datetime | None = None

async def load_user_settings_to_cache(session_factory: sessionmaker) -> None:
    logger.info("Loading user settings into cache...")
    async with session_factory() as session:
        result = await session.execute(select(UserSettings))
        user_settings_list = result.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = {
                "language": settings_row.language,
                "notification_settings": settings_row.notification_settings,
                "mute_settings": {"muted_users": set(settings_row.muted_users.split(",")) if settings_row.muted_users else set(), "mute_all": settings_row.mute_all},
                "teamtalk_username": settings_row.teamtalk_username,
                "not_on_online_enabled": settings_row.not_on_online_enabled,
                "not_on_online_confirmed": settings_row.not_on_online_confirmed,
            }
    logger.info(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")

async def _async_load_user_settings(telegram_id: int, session: AsyncSession):
    user_settings_row = await session.get(UserSettings, telegram_id)
    if user_settings_row:
        USER_SETTINGS_CACHE[telegram_id] = {
            "language": user_settings_row.language,
            "notification_settings": user_settings_row.notification_settings,
            "mute_settings": {"muted_users": set(user_settings_row.muted_users.split(",")) if user_settings_row.muted_users else set(), "mute_all": user_settings_row.mute_all},
            "teamtalk_username": user_settings_row.teamtalk_username,
            "not_on_online_enabled": user_settings_row.not_on_online_enabled,
            "not_on_online_confirmed": user_settings_row.not_on_online_confirmed,
        }
    else:
        default_settings_data = {
            "language": "en",
            "notification_settings": NotificationSetting.ALL,
            "mute_settings": {"muted_users": set(), "mute_all": False},
            "teamtalk_username": None,
            "not_on_online_enabled": False,
            "not_on_online_confirmed": False,
        }
        USER_SETTINGS_CACHE[telegram_id] = default_settings_data
        new_settings_row = UserSettings(
            telegram_id=telegram_id,
            language=default_settings_data["language"],
            notification_settings=default_settings_data["notification_settings"],
            muted_users="",
            mute_all=default_settings_data["mute_settings"]["mute_all"],
            teamtalk_username=default_settings_data["teamtalk_username"],
            not_on_online_enabled=default_settings_data["not_on_online_enabled"],
            not_on_online_confirmed=default_settings_data["not_on_online_confirmed"],
        )
        session.add(new_settings_row)
        await session.commit()
        logger.info(f"Created default settings for user {telegram_id}")

async def db_add(session: AsyncSession, model: Base, **kwargs):
    try:
        if model in [SubscribedUser, Admin] and "telegram_id" in kwargs:
             existing_record = await session.get(model, kwargs["telegram_id"])
             if existing_record:
                 logger.warning(f"Record already exists in {model.__tablename__} for id {kwargs['telegram_id']}")
                 return False

        new_db_record = model(**kwargs)
        session.add(new_db_record)
        await session.commit()
        logger.info(f"Added record to {model.__tablename__}: {kwargs}")
        return True
    except Exception as e:
        logger.error(f"Error adding to DB ({model.__tablename__}): {e}")
        await session.rollback()
        return False

async def db_remove(session: AsyncSession, model: Base, telegram_id: int):
    try:
        record_to_remove = await session.get(model, telegram_id)
        if record_to_remove:
            await session.delete(record_to_remove)
            await session.commit()
            logger.info(f"Removed record from {model.__tablename__} for id {telegram_id}")
            return True
        logger.warning(f"Record not found in {model.__tablename__} for id {telegram_id}")
        return False
    except Exception as e:
        logger.error(f"Error removing from DB ({model.__tablename__}): {e}")
        await session.rollback()
        return False

async def db_get_all_telegram_ids(session: AsyncSession, model: Base) -> list[int]:
    try:
        result = await session.execute(select(model.telegram_id))
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Error getting telegram_ids from DB ({model.__tablename__}): {e}")
        return []

async def add_subscriber(session: AsyncSession, telegram_id: int):
    return await db_add(session, SubscribedUser, telegram_id=telegram_id)

async def remove_subscriber(session: AsyncSession, telegram_id: int):
    return await db_remove(session, SubscribedUser, telegram_id)

async def get_all_subscribers(session: AsyncSession):
    return await db_get_all_telegram_ids(session, SubscribedUser)

async def add_admin(session: AsyncSession, telegram_id: int):
    return await db_add(session, Admin, telegram_id=telegram_id)

async def remove_admin_db(session: AsyncSession, telegram_id: int):
    return await db_remove(session, Admin, telegram_id)

async def get_all_admins(session: AsyncSession) -> list[int]:
    return await db_get_all_telegram_ids(session, Admin)

async def is_admin(session: AsyncSession, telegram_id: int) -> bool:
    admin_db_record = await session.get(Admin, telegram_id)
    return admin_db_record is not None

async def create_deeplink(session: AsyncSession, action: str, payload: str | None = None, expected_telegram_id: int | None = None) -> str:
    token_str = str(uuid.uuid4())
    expiry_time_val = datetime.utcnow() + timedelta(minutes=5)
    deeplink_obj = Deeplink(
        token=token_str,
        action=action,
        payload=payload,
        expected_telegram_id=expected_telegram_id,
        expiry_time=expiry_time_val
    )
    session.add(deeplink_obj)
    await session.commit()
    logger.info(f"Created deeplink: token={token_str}, action={action}, payload={payload}, expected_id={expected_telegram_id}")
    return token_str

async def get_deeplink(session: AsyncSession, token: str) -> Deeplink | None:
    result = await session.execute(select(Deeplink).where(Deeplink.token == token))
    deeplink_obj = result.scalar_one_or_none()
    if deeplink_obj and deeplink_obj.expiry_time and deeplink_obj.expiry_time < datetime.utcnow():
        logger.warning(f"Deeplink {token} expired.")
        await session.delete(deeplink_obj)
        await session.commit()
        return None
    return deeplink_obj

async def delete_deeplink(session: AsyncSession, token: str):
    stmt = delete(Deeplink).where(Deeplink.token == token)
    result = await session.execute(stmt)
    await session.commit()
    if result.rowcount > 0:
        logger.info(f"Deleted deeplink {token}")
    else:
        logger.warning(f"Deeplink {token} not found for deletion.")

tt_bot = pytalk.TeamTalkBot(client_name=config["CLIENT_NAME"])
current_tt_instance: TeamTalkInstance | None = None

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: sessionmaker):
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)

class UserSettingsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_obj = data.get("event_from_user")
        session_obj: AsyncSession | None = data.get("session")

        if user_obj and session_obj:
            telegram_id_val = user_obj.id
            if telegram_id_val not in USER_SETTINGS_CACHE:
                await _async_load_user_settings(telegram_id_val, session_obj)

            user_settings_data = USER_SETTINGS_CACHE.get(telegram_id_val, {
                "language": "en",
                "notification_settings": NotificationSetting.ALL,
                "mute_settings": {"muted_users": set(), "mute_all": False},
                "teamtalk_username": None,
                "not_on_online_enabled": False,
                "not_on_online_confirmed": False,
            })
            data["user_settings"] = user_settings_data
        else:
            data["user_settings"] = {
                "language": "en",
                "notification_settings": NotificationSetting.ALL,
                "mute_settings": {"muted_users": set(), "mute_all": False},
                "teamtalk_username": None,
                "not_on_online_enabled": False,
                "not_on_online_confirmed": False,
            }
        current_user_settings = data["user_settings"]
        data["language"] = current_user_settings.get("language", "en")
        data["notification_settings"] = current_user_settings.get("notification_settings", NotificationSetting.ALL)
        data["mute_settings"] = current_user_settings.get("mute_settings", {"muted_users": set(), "mute_all": False})

        return await handler(event, data)

class TeamTalkInstanceMiddleware(BaseMiddleware):
    def __init__(self, tt_bot_instance: pytalk.TeamTalkBot):
        super().__init__()
        self.tt_bot_instance = tt_bot_instance

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["tt_instance"] = current_tt_instance
        return await handler(event, data)

class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user_obj = event.from_user
        if not user_obj:
            return False
        return await is_admin(session, user_obj.id)

async def send_telegram_message(
    token: str,
    chat_id: int,
    text: str,
    language: str = "en",
    reply_tt: Callable | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    tt_instance_for_check: TeamTalkInstance | None = None
) -> bool:
    bot_to_use = tg_bot_event if token == config["TG_EVENT_TOKEN"] else tg_bot_message
    if not bot_to_use:
        logger.error(f"No Telegram bot instance available for token: {token}")
        if reply_tt:
            reply_tt("Failed to send message: Invalid token.")
        return False

    send_silently = False
    recipient_settings = USER_SETTINGS_CACHE.get(chat_id)

    if recipient_settings and \
       recipient_settings.get("not_on_online_enabled") and \
       recipient_settings.get("not_on_online_confirmed") and \
       recipient_settings.get("teamtalk_username") and \
       tt_instance_for_check:

        tt_username_to_check = recipient_settings["teamtalk_username"]
        try:
            is_tt_user_online = False
            if tt_instance_for_check.connected and tt_instance_for_check.logged_in:
                all_online_users = tt_instance_for_check.server.get_users()
                for online_user in all_online_users:
                    if ttstr(online_user.username) == tt_username_to_check:
                        is_tt_user_online = True
                        break
            else:
                logger.warning(f"Cannot check TT status for {tt_username_to_check}, TT instance not ready for chat_id {chat_id}.")


            if is_tt_user_online:
                send_silently = True
                logger.info(f"Sending message to {chat_id} silently as their linked TT user '{tt_username_to_check}' is online.")
        except Exception as e:
            logger.warning(f"Could not check TeamTalk status for user '{tt_username_to_check}' (TG ID: {chat_id}): {e}")

    message_sent = False
    try:
        await bot_to_use.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_notification=send_silently
            )
        message_sent = True

    except (TelegramForbiddenError, TelegramAPIError) as e:
        if "bot was blocked by the user" in str(e).lower():
            logger.warning(f"User {chat_id} blocked the bot. Unsubscribing...")
            try:
                async with SessionFactory() as unsubscribe_session:
                    removed = await remove_subscriber(unsubscribe_session, chat_id)
                if removed:
                    logger.info(f"Successfully unsubscribed blocked user {chat_id}.")
                else:
                    logger.info(f"User {chat_id} was likely already unsubscribed (remove_subscriber returned False).")

                USER_SETTINGS_CACHE.pop(chat_id, None)
                logger.info(f"Removed user {chat_id} from settings cache.")

            except Exception as db_err:
                logger.error(f"Failed to unsubscribe blocked user {chat_id} from DB: {db_err}")
            message_sent = False

        else:
            logger.error(f"Telegram API error sending to {chat_id}: {e}")
            if reply_tt:
                reply_tt(f"Failed to send message: Telegram API Error: {e}")
            message_sent = False

    except Exception as e:
        logger.error(f"Error sending Telegram message to {chat_id}: {e}")
        if reply_tt:
            reply_tt(f"Failed to send message: {e}")
        message_sent = False

    if message_sent and reply_tt:
        reply_tt("Message sent to Telegram successfully." if language == "en" else "Сообщение успешно отправлено в Telegram.")

    return message_sent


async def send_telegram_messages(
    token: str,
    chat_ids: list[int],
    text_generator: Callable[[str], str],
    session: AsyncSession,
    reply_markup_generator: Callable[[str, str, str, int], InlineKeyboardMarkup | None] | None = None,
    tt_user_username_for_markup: str | None = None,
    tt_user_nickname_for_markup: str | None = None,
    tt_instance_for_check: TeamTalkInstance | None = None
):
    tasks_list = []
    for chat_id_val in chat_ids:
        user_settings_val = USER_SETTINGS_CACHE.get(chat_id_val)
        language_val = user_settings_val.get("language", "en") if user_settings_val else "en"
        text_val = text_generator(language_val)

        current_reply_markup_val = None
        if reply_markup_generator and tt_user_username_for_markup and tt_user_nickname_for_markup:
            current_reply_markup_val = reply_markup_generator(tt_user_username_for_markup, tt_user_nickname_for_markup, language_val, chat_id_val)

        tasks_list.append(send_telegram_message(
            token,
            chat_id_val,
            text_val,
            language_val,
            reply_markup=current_reply_markup_val,
            tt_instance_for_check=tt_instance_for_check
            ))
    await asyncio.gather(*tasks_list)

user_commands_router = Router(name="user_commands")
settings_router = Router(name="settings")
admin_router = Router(name="admin_commands")
callback_router = Router(name="callbacks")
catch_all_router = Router(name="catch_all")

@user_commands_router.message(Command("start"))
async def start_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_settings: dict
):
    token_val = command.args
    if token_val:
        await handle_deeplink(message, token_val, session, language, user_settings)
    else:
        await handle_start_command(message, language)

async def handle_start_command(message: Message, language: str):
    await message.reply("Hello! Use /help to see available commands." if language == "en" else "Привет! Используйте /help для просмотра доступных команд.")

async def handle_deeplink(message: Message, token: str, session: AsyncSession, language: str, user_settings: dict):
    deeplink_obj = await get_deeplink(session, token)
    if not deeplink_obj:
        await message.reply("Invalid or expired deeplink." if language == "en" else "Недействительная или истекшая ссылка.")
        return

    telegram_id_val = message.from_user.id
    reply_text_val = "An error occurred." if language == "en" else "Произошла ошибка."

    if deeplink_obj.expected_telegram_id and deeplink_obj.expected_telegram_id != telegram_id_val:
        await message.reply("This confirmation link was intended for a different Telegram account." if language == "en" else "Эта ссылка для подтверждения предназначена для другого Telegram аккаунта.")
        return

    if deeplink_obj.action == "subscribe":
        if await add_subscriber(session, telegram_id_val):
            reply_text_val = "You have successfully subscribed to notifications." if language == "en" else "Вы успешно подписались на уведомления."
            logger.info(f"User {telegram_id_val} subscribed via deeplink {token}")
        else:
            reply_text_val = "You are already subscribed to notifications." if language == "en" else "Вы уже подписаны на уведомления."
    elif deeplink_obj.action == "unsubscribe":
        if await remove_subscriber(session, telegram_id_val):
            reply_text_val = "You have successfully unsubscribed from notifications." if language == "en" else "Вы успешно отписались от уведомления."
            logger.info(f"User {telegram_id_val} unsubscribed via deeplink {token}")
            USER_SETTINGS_CACHE.pop(telegram_id_val, None)
            logger.info(f"Removed user {telegram_id_val} from settings cache after unsubscribe.")
        else:
            reply_text_val = "You were not subscribed to notifications." if language == "en" else "Вы не были подписаны на уведомления."
    elif deeplink_obj.action == "confirm_not_on_online":
        tt_username_from_payload = deeplink_obj.payload
        if not tt_username_from_payload:
            reply_text_val = "Error: Missing TeamTalk username in confirmation link." if language == "en" else "Ошибка: В ссылке подтверждения отсутствует имя пользователя TeamTalk."
            logger.error(f"Deeplink {token} for 'confirm_not_on_online' missing payload.")
        else:
            db_user_settings = await session.get(UserSettings, telegram_id_val)
            if not db_user_settings:
                db_user_settings = UserSettings(telegram_id=telegram_id_val)
                session.add(db_user_settings)

            db_user_settings.teamtalk_username = tt_username_from_payload
            db_user_settings.not_on_online_enabled = True
            db_user_settings.not_on_online_confirmed = True
            await session.commit()

            if telegram_id_val in USER_SETTINGS_CACHE:
                USER_SETTINGS_CACHE[telegram_id_val]["teamtalk_username"] = tt_username_from_payload
                USER_SETTINGS_CACHE[telegram_id_val]["not_on_online_enabled"] = True
                USER_SETTINGS_CACHE[telegram_id_val]["not_on_online_confirmed"] = True
            else:
                await _async_load_user_settings(telegram_id_val, session)

            reply_text_val = (f"'Not on online' notifications enabled for TeamTalk user '{html.quote(tt_username_from_payload)}'. "
                              "You will receive silent notifications when this user is online on TeamTalk."
                              if language == "en" else
                              f"Уведомления 'не в сети' включены для пользователя TeamTalk '{html.quote(tt_username_from_payload)}'. "
                              "Вы будете получать тихие уведомления, когда этот пользователь в сети TeamTalk.")
            logger.info(f"User {telegram_id_val} confirmed 'not on online' for TT user {tt_username_from_payload} via deeplink {token}")
    else:
        reply_text_val = "Invalid deeplink action." if language == "en" else "Неверное действие deeplink."
        logger.warning(f"Invalid deeplink action '{deeplink_obj.action}' for token {token}")

    await message.reply(reply_text_val)
    await delete_deeplink(session, token)

@user_commands_router.message(Command("who"))
async def who_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None,
    session: AsyncSession
):
    if not tt_instance:
        await message.reply("TeamTalk bot is not connected." if language == "en" else "Бот TeamTalk не подключен.")
        return

    try:
        all_users_list = tt_instance.server.get_users()
    except Exception as e:
        logger.error(f"Failed to get users from TT: {e}")
        await message.reply("Error getting users from TeamTalk." if language == "en" else "Ошибка получения пользователей из TeamTalk.")
        return

    is_caller_admin_val = await is_admin(session, message.from_user.id)

    users_to_display_count_val = 0
    channels_display_data_val: dict[str, list[str]] = {}

    for user_obj in all_users_list:
        channel_obj = user_obj.channel
        user_display_channel_name_val = ""

        is_channel_hidden_val = False
        if channel_obj:
            try:
                if (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0:
                    is_channel_hidden_val = True
            except AttributeError:
                logger.warning(f"Could not determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden.")
            except Exception as e_chan:
                 logger.error(f"Error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}")

        if is_caller_admin_val:
            if channel_obj and channel_obj.id != 1 and channel_obj.id != 0 and channel_obj.id != -1:
                user_display_channel_name_val = (f"in {ttstr(channel_obj.name)}" if language == "en"
                                             else f"в {ttstr(channel_obj.name)}")
            elif not channel_obj or channel_obj.id in [0, -1]:
                user_display_channel_name_val = ("under server" if language == "en"
                                             else "под сервером")
            else:
                user_display_channel_name_val = ("in root channel" if language == "en"
                                             else "в корневом канале")
        elif is_channel_hidden_val:
            user_display_channel_name_val = ("under server" if language == "en"
                                         else "под сервером")
        elif channel_obj and channel_obj.id != 1 and channel_obj.id != 0 and channel_obj.id != -1:
            user_display_channel_name_val = (f"in {ttstr(channel_obj.name)}" if language == "en"
                                         else f"в {ttstr(channel_obj.name)}")
        elif not channel_obj or channel_obj.id in [0, -1]:
            user_display_channel_name_val = ("under server" if language == "en"
                                         else "под сервером")
        else:
            user_display_channel_name_val = ("in root channel" if language == "en"
                                         else "в корневом канале")

        if not user_display_channel_name_val:
            user_display_channel_name_val = ("in unknown location" if language == "en" else "в неизвестном месте")


        if user_display_channel_name_val not in channels_display_data_val:
            channels_display_data_val[user_display_channel_name_val] = []

        user_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or ("unknown user" if language == "en" else "неизвестный пользователь")
        channels_display_data_val[user_display_channel_name_val].append(user_nickname_val)
        users_to_display_count_val += 1

    user_count_val = users_to_display_count_val
    channel_info_parts_val = []

    for display_channel_name_val, users_in_channel_list_val in channels_display_data_val.items():
        user_text_segment_val = ""
        if users_in_channel_list_val:
            if len(users_in_channel_list_val) > 1:
                user_separator_val = " and " if language == "en" else " и "
                user_list_except_last_segment_val = ", ".join(users_in_channel_list_val[:-1])
                user_text_segment_val = f"{user_list_except_last_segment_val}{user_separator_val}{users_in_channel_list_val[-1]}"
            else:
                user_text_segment_val = users_in_channel_list_val[0]
            channel_info_parts_val.append(f"{user_text_segment_val} {display_channel_name_val}")

    users_word_total_localized_val = {
        "en": "user" if user_count_val == 1 else "users",
        "ru": "пользователь" if user_count_val == 1 else ("пользователя" if 1 < user_count_val < 5 else "пользователей")
    }
    users_word_total_val = users_word_total_localized_val[language]

    text_localized_val = {
        "en": f"There are {user_count_val} {users_word_total_val} on the server:\n",
        "ru": f"На сервере сейчас {user_count_val} {users_word_total_val}:\n"
    }
    text_reply = text_localized_val[language]

    if channel_info_parts_val:
        text_reply += "\n".join(channel_info_parts_val)
    else:
         text_reply += "No users found online." if language == "en" else "Пользователей онлайн не найдено."

    await message.reply(text_reply)

@user_commands_router.message(Command("id"))
async def id_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await show_user_buttons(message, "id", language, tt_instance)

@user_commands_router.message(Command("help"))
async def help_command_handler(message: Message, language: str):
    help_text_val = get_help_text(language)
    await message.reply(help_text_val)

@settings_router.message(Command("cl"))
async def cl_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str
):
    if not command.args or command.args.lower() not in ["en", "ru"]:
        await message.reply("Please specify the language. Example: /cl en or /cl ru." if language == "en" else "Укажите язык. Пример: /cl en или /cl ru.")
        return

    new_lang_val = command.args.lower()
    telegram_id_val = message.from_user.id

    user_settings_obj = await session.get(UserSettings, telegram_id_val)
    if not user_settings_obj:
        user_settings_obj = UserSettings(telegram_id=telegram_id_val, language=new_lang_val)
        session.add(user_settings_obj)
    else:
        user_settings_obj.language = new_lang_val
    await session.commit()

    if telegram_id_val in USER_SETTINGS_CACHE:
        USER_SETTINGS_CACHE[telegram_id_val]["language"] = new_lang_val
    else:
         await _async_load_user_settings(telegram_id_val, session)

    await message.reply(f"Language changed to {new_lang_val}." if new_lang_val == "en" else f"Язык изменен на {new_lang_val}.")

async def set_notification_settings_command(message: Message, settings_val: NotificationSetting, session: AsyncSession, language: str):
    telegram_id_val = message.from_user.id
    user_settings_obj = await session.get(UserSettings, telegram_id_val)
    if not user_settings_obj:
        user_settings_obj = UserSettings(telegram_id=telegram_id_val, notification_settings=settings_val)
        session.add(user_settings_obj)
    else:
        user_settings_obj.notification_settings = settings_val
    await session.commit()

    if telegram_id_val in USER_SETTINGS_CACHE:
        USER_SETTINGS_CACHE[telegram_id_val]["notification_settings"] = settings_val
    else:
         await _async_load_user_settings(telegram_id_val, session)

    settings_messages_map = {
        NotificationSetting.ALL: "Join and leave notifications are enabled." if language == "en" else "Уведомления о входах и выходах включены.",
        NotificationSetting.JOIN_OFF: "Only leave notifications are enabled." if language == "en" else "Включены только уведомления о выходах.",
        NotificationSetting.LEAVE_OFF: "Only join notifications are enabled." if language == "en" else "Включены только уведомления о входах.",
        NotificationSetting.NONE: "Join and leave notifications are disabled." if language == "en" else "Уведомления о входах и выходах отключены.",
    }
    await message.reply(settings_messages_map[settings_val])

@settings_router.message(Command("notify_all"))
async def notify_all_cmd(message: Message, session: AsyncSession, language: str):
    await set_notification_settings_command(message, NotificationSetting.ALL, session, language)

@settings_router.message(Command("notify_join_off"))
async def notify_join_off_cmd(message: Message, session: AsyncSession, language: str):
    await set_notification_settings_command(message, NotificationSetting.JOIN_OFF, session, language)

@settings_router.message(Command("notify_leave_off"))
async def notify_leave_off_cmd(message: Message, session: AsyncSession, language: str):
    await set_notification_settings_command(message, NotificationSetting.LEAVE_OFF, session, language)

@settings_router.message(Command("notify_none"))
async def notify_none_cmd(message: Message, session: AsyncSession, language: str):
    await set_notification_settings_command(message, NotificationSetting.NONE, session, language)

async def update_mute_settings_db(session: AsyncSession, telegram_id: int, muted_users_set: set, mute_all_flag: bool):
    user_settings_obj = await session.get(UserSettings, telegram_id)
    muted_users_str_val = ",".join(sorted(list(muted_users_set)))
    if not user_settings_obj:
        user_settings_obj = UserSettings(telegram_id=telegram_id, muted_users=muted_users_str_val, mute_all=mute_all_flag)
        session.add(user_settings_obj)
    else:
        user_settings_obj.muted_users = muted_users_str_val
        user_settings_obj.mute_all = mute_all_flag
    await session.commit()
    if telegram_id in USER_SETTINGS_CACHE:
        USER_SETTINGS_CACHE[telegram_id]["mute_settings"] = {"muted_users": muted_users_set, "mute_all": mute_all_flag}
    else:
        await _async_load_user_settings(telegram_id, session)

async def update_mute_user_list(session: AsyncSession, telegram_id: int, username_to_process: str, action: str, current_mute_settings: dict):
    muted_users_val = current_mute_settings["muted_users"].copy()
    mute_all_val = current_mute_settings["mute_all"]

    if action == "mute":
        muted_users_val.add(username_to_process)
    elif action == "unmute":
        muted_users_val.discard(username_to_process)

    await update_mute_settings_db(session, telegram_id, muted_users_val, mute_all_val)

async def set_mute_all(session: AsyncSession, telegram_id: int, mute_all_flag: bool, current_mute_settings: dict):
    muted_users_val = current_mute_settings["muted_users"] if mute_all_flag else set()
    await update_mute_settings_db(session, telegram_id, muted_users_val, mute_all_flag)

@settings_router.message(Command("mute"))
async def mute_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    mute_settings: dict
):
    args_val = command.args
    if not args_val or not args_val.startswith("user "):
        await message.reply("Please specify username to mute in format: /mute user <username>." if language == "en" else "Пожалуйста, укажите имя пользователя для мьюта в формате: /mute user <username>.")
        return

    username_to_mute_val = args_val[len("user "):].strip()
    if not username_to_mute_val:
         await message.reply("Username cannot be empty." if language == "en" else "Имя пользователя не может быть пустым.")
         return

    telegram_id_val = message.from_user.id
    was_already_muted = username_to_mute_val in mute_settings["muted_users"]

    if was_already_muted:
        await message.reply(f"User {html.quote(username_to_mute_val)} was already muted." if language == "en" else f"Пользователь {html.quote(username_to_mute_val)} уже был замьючен.")
    else:
        await update_mute_user_list(session, telegram_id_val, username_to_mute_val, "mute", mute_settings)
        await message.reply(f"User {html.quote(username_to_mute_val)} is now muted." if language == "en" else f"Пользователь {html.quote(username_to_mute_val)} теперь замьючен.")

@settings_router.message(Command("unmute"))
async def unmute_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    mute_settings: dict
):
    args_val = command.args
    if not args_val or not args_val.startswith("user "):
        await message.reply("Please specify username to unmute in format: /unmute user <username>." if language == "en" else "Пожалуйста, укажите имя пользователя для размьюта в формате: /unmute user <username>.")
        return

    username_to_unmute_val = args_val[len("user "):].strip()
    if not username_to_unmute_val:
         await message.reply("Username cannot be empty." if language == "en" else "Имя пользователя не может быть пустым.")
         return

    telegram_id_val = message.from_user.id
    was_muted = username_to_unmute_val in mute_settings["muted_users"]

    if was_muted:
        await update_mute_user_list(session, telegram_id_val, username_to_unmute_val, "unmute", mute_settings)
        await message.reply(f"User {html.quote(username_to_unmute_val)} is now unmuted." if language == "en" else f"Пользователь {html.quote(username_to_unmute_val)} теперь размьючен.")
    else:
        await message.reply(f"User {html.quote(username_to_unmute_val)} was not in the mute list." if language == "en" else f"Пользователь {html.quote(username_to_unmute_val)} не был в списке мьюта.")


@settings_router.message(Command("mute_all"))
async def mute_all_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    mute_settings: dict
):
    await set_mute_all(session, message.from_user.id, True, mute_settings)
    await message.reply("Mute all for join/leave notifications enabled (only exceptions will be notified)." if language == "en" else "Мьют всех для уведомлений о входе/выходе включен (уведомления будут приходить только для исключений).")

@settings_router.message(Command("unmute_all"))
async def unmute_all_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    mute_settings: dict
):
    await set_mute_all(session, message.from_user.id, False, mute_settings)
    await message.reply("Mute all for join/leave notifications disabled (muted users won't be notified)." if language == "en" else "Мьют всех для уведомлений о входе/выходе выключен (замьюченные пользователи не будут получать уведомления).")

@settings_router.message(Command("toggle_noon"))
async def toggle_noon_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_settings: dict
):
    telegram_id = message.from_user.id
    current_teamtalk_username = user_settings.get("teamtalk_username")
    current_enabled_status = user_settings.get("not_on_online_enabled", False)
    current_confirmed_status = user_settings.get("not_on_online_confirmed", False)

    if not current_teamtalk_username or not current_confirmed_status:
        await message.reply("The 'not on online' feature is not configured for your account. "
                            "Please set it up via TeamTalk using `/not on online`."
                            if language == "en" else
                            "Функция 'не в сети' не настроена для вашего аккаунта. "
                            "Пожалуйста, настройте ее через TeamTalk командой `/not on online`.")
        return

    new_enabled_status = not current_enabled_status

    db_user_settings = await session.get(UserSettings, telegram_id)
    if db_user_settings:
        db_user_settings.not_on_online_enabled = new_enabled_status
        await session.commit()

        if telegram_id in USER_SETTINGS_CACHE:
            USER_SETTINGS_CACHE[telegram_id]["not_on_online_enabled"] = new_enabled_status
        else:
            await _async_load_user_settings(telegram_id, session)

        if new_enabled_status:
            reply_text = (f"'Not on online' notifications are now ENABLED for TeamTalk user '{html.quote(current_teamtalk_username)}'. "
                          "You will receive silent notifications when this user is online."
                          if language == "en" else
                          f"Уведомления 'не в сети' теперь ВКЛЮЧЕНЫ для пользователя TeamTalk '{html.quote(current_teamtalk_username)}'. "
                          "Вы будете получать тихие уведомления, когда этот пользователь в сети.")
        else:
            reply_text = (f"'Not on online' notifications are now DISABLED for TeamTalk user '{html.quote(current_teamtalk_username)}'. "
                          "Notifications will be sent normally."
                          if language == "en" else
                          f"Уведомления 'не в сети' теперь ВЫКЛЮЧЕНЫ для пользователя TeamTalk '{html.quote(current_teamtalk_username)}'. "
                          "Уведомления будут приходить как обычно.")
        logger.info(f"User {telegram_id} toggled 'not on online' to {new_enabled_status} for TT user {current_teamtalk_username}")
    else:
        reply_text = "Error updating settings. Please try again." if language == "en" else "Ошибка обновления настроек. Пожалуйста, попробуйте снова."
        logger.error(f"Could not find UserSettings for {telegram_id} during toggle_noon.")

    await message.reply(reply_text)

@settings_router.message(Command("my_noon_status"))
async def my_noon_status_command_handler(
    message: Message,
    language: str,
    user_settings: dict
):
    telegram_id = message.from_user.id
    tt_username = user_settings.get("teamtalk_username")
    enabled = user_settings.get("not_on_online_enabled", False)
    confirmed = user_settings.get("not_on_online_confirmed", False)

    if not tt_username or not confirmed:
        reply_text = ("'Not on online' feature is not configured for your account. "
                      "Use `/not on online` in TeamTalk to set it up."
                      if language == "en" else
                      "Функция 'не в сети' не настроена для вашего аккаунта. "
                      "Используйте `/not on online` в TeamTalk для настройки.")
    else:
        status_text = "ENABLED" if enabled else "DISABLED"
        status_text_ru = "ВКЛЮЧЕНА" if enabled else "ВЫКЛЮЧЕНА"
        reply_text = (f"'Not on online' notifications are {status_text} for TeamTalk user '{html.quote(tt_username)}'."
                      if language == "en" else
                      f"Уведомления 'не в сети' {status_text_ru} для пользователя TeamTalk '{html.quote(tt_username)}'.")
    await message.reply(reply_text)


admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())

@admin_router.message(Command("kick"))
async def kick_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await show_user_buttons(message, "kick", language, tt_instance)

@admin_router.message(Command("ban"))
async def ban_command_handler(
    message: Message,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await show_user_buttons(message, "ban", language, tt_instance)

@callback_router.callback_query(F.data.startswith("id:") | F.data.startswith("kick:") | F.data.startswith("ban:"))
async def process_user_selection(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    tt_instance: TeamTalkInstance | None
):
    await callback_query.answer()

    try:
        action_val, user_id_str_val, user_nickname_val = callback_query.data.split(":", 2)
        user_id_val = int(user_id_str_val)
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format: {callback_query.data}")
        await callback_query.message.edit_text("Invalid data received." if language == "en" else "Получены неверные данные.")
        return

    if not tt_instance:
         await callback_query.message.edit_text("TeamTalk bot is not connected." if language == "en" else "Бот TeamTalk не подключен.")
         return

    reply_text_val = "Unknown action." if language == "en" else "Неизвестное действие."

    if action_val == "id":
        reply_text_val = (f"User {html.quote(user_nickname_val)} has ID: {user_id_val}" if language == "en"
                      else f"Пользователь {html.quote(user_nickname_val)} имеет ID: {user_id_val}")

    elif action_val in ["kick", "ban"]:
        if not await is_admin(session, callback_query.from_user.id):
            await callback_query.answer("You do not have permission to execute this action." if language == "en" else "У вас нет прав на выполнение этого действия.", show_alert=True)
            return

        try:
            user_to_act_on = tt_instance.server.get_user(user_id_val)
        except Exception as e:
            logger.error(f"Failed to get user {user_id_val} from TT for {action_val}: {e}")
            await callback_query.message.edit_text("Error finding user on TeamTalk." if language == "en" else "Ошибка поиска пользователя в TeamTalk.")
            return

        if user_to_act_on:
            action_past_tense_en = "kicked" if action_val == "kick" else "banned"
            action_past_tense_ru_val = "исключен" if action_val == "kick" else "забанен"
            action_gerund_ru_val = "исключения" if action_val == "kick" else "бана"

            try:
                if action_val == "ban":
                    user_to_act_on.ban(from_server=True)
                user_to_act_on.kick(from_server=True)

                if action_val == "ban":
                     reply_text_val = (f"User {html.quote(user_nickname_val)} banned and kicked from server." if language == "en"
                                   else f"Пользователь {html.quote(user_nickname_val)} был забанен и выкинут с сервера.")
                else:
                     reply_text_val = (f"User {html.quote(user_nickname_val)} kicked from server." if language == "en"
                                   else f"Пользователь {html.quote(user_nickname_val)} был исключен с сервера.")
                logger.info(f"Admin {callback_query.from_user.id} {action_past_tense_en} user {user_nickname_val} ({user_id_val})")

            except Exception as e:
                reply_text_val = (f"Error {action_val}ing user {html.quote(user_nickname_val)}: {e}" if language == "en"
                              else f"Ошибка {action_gerund_ru_val} пользователя {html.quote(user_nickname_val)}: {e}")
                logger.error(f"Error {action_val}ing user {user_nickname_val} ({user_id_val}): {e}")
        else:
            reply_text_val = "User not found on server anymore." if language == "en" else "Пользователь больше не найден на сервере."
    else:
         logger.warning(f"Unhandled action '{action_val}' in callback query.")

    await callback_query.message.edit_text(reply_text_val, reply_markup=None)

@callback_router.callback_query(F.data.startswith("toggle_ignore_user:"))
async def process_toggle_ignore_user(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    mute_settings: dict
):
    telegram_id_val = callback_query.from_user.id

    try:
        _, tt_username_to_toggle_val, nickname_from_callback_val = callback_query.data.split(":", 2)
        tt_username_to_toggle_val = tt_username_to_toggle_val.strip()
        nickname_from_callback_val = nickname_from_callback_val.strip()
    except ValueError:
        logger.error(f"Invalid callback data for toggle_ignore_user: {callback_query.data} from user {telegram_id_val}")
        await callback_query.answer("Error processing request.", show_alert=True)
        return

    if not tt_username_to_toggle_val:
        logger.error(f"Empty username in toggle_ignore_user callback: {callback_query.data} from user {telegram_id_val}")
        await callback_query.answer("Error: Empty username.", show_alert=True)
        return

    current_muted_users_val = mute_settings.get("muted_users", set()).copy()
    current_mute_all_val = mute_settings.get("mute_all", False)

    new_muted_users_val = current_muted_users_val

    if current_mute_all_val:
        if tt_username_to_toggle_val in new_muted_users_val:
            new_muted_users_val.discard(tt_username_to_toggle_val)
        else:
            new_muted_users_val.add(tt_username_to_toggle_val)
    elif tt_username_to_toggle_val in new_muted_users_val:
        new_muted_users_val.discard(tt_username_to_toggle_val)
    else:
        new_muted_users_val.add(tt_username_to_toggle_val)

    await update_mute_settings_db(session, telegram_id_val, new_muted_users_val, current_mute_all_val)

    user_is_now_effectively_ignored_val = False
    if current_mute_all_val:
        user_is_now_effectively_ignored_val = tt_username_to_toggle_val not in new_muted_users_val
    else:
        user_is_now_effectively_ignored_val = tt_username_to_toggle_val in new_muted_users_val

    if user_is_now_effectively_ignored_val:
        feedback_msg_for_answer_val = f"User {html.quote(nickname_from_callback_val)} is now ignored." if language == "en" \
                       else f"Пользователь {html.quote(nickname_from_callback_val)} теперь игнорируется."
    else:
        feedback_msg_for_answer_val = f"User {html.quote(nickname_from_callback_val)} is no longer ignored." if language == "en" \
                       else f"Пользователь {html.quote(nickname_from_callback_val)} больше не игнорируется."

    button_display_nickname_new_val = html.quote(nickname_from_callback_val)
    button_text_en_new_val = f"Toggle ignore status: {button_display_nickname_new_val}"
    button_text_ru_new_val = f"Переключить статус игнорирования: {button_display_nickname_new_val}"
    button_text_new_val = button_text_ru_new_val if language == "ru" else button_text_en_new_val

    callback_data_new_val = f"toggle_ignore_user:{tt_username_to_toggle_val}:{nickname_from_callback_val}"

    new_keyboard_val = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text_new_val, callback_data=callback_data_new_val)]
    ])

    try:
        await callback_query.message.edit_reply_markup(reply_markup=new_keyboard_val)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.info(f"Button markup for {nickname_from_callback_val} was not modified, as expected for static button text.")
        else:
            logger.error(f"TelegramBadRequest editing ignore button for {nickname_from_callback_val}: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing ignore button for {nickname_from_callback_val}: {e}")

    try:
        await callback_query.answer(text=feedback_msg_for_answer_val, show_alert=False)
    except TelegramAPIError as e:
        logger.warning(f"Could not send feedback answer for toggle_ignore_user for {nickname_from_callback_val}: {e}")


async def show_user_buttons(message: Message, command_type: str, language: str, tt_instance: TeamTalkInstance | None):
    if not tt_instance:
        await message.reply("TeamTalk bot is not connected." if language == "en" else "Бот TeamTalk не подключен.")
        return

    try:
        users_list = tt_instance.server.get_users()
    except Exception as e:
        logger.error(f"Failed to get users from TT for {command_type}: {e}")
        await message.reply("Error getting users from TeamTalk." if language == "en" else "Ошибка получения пользователей из TeamTalk.")
        return

    if not users_list:
        await message.reply("No users online to select." if language == "en" else "Нет пользователей онлайн для выбора.")
        return

    builder = InlineKeyboardBuilder()
    my_user_id_val = tt_instance.getMyUserID()
    for user_obj in users_list:
        if user_obj.id == my_user_id_val:
            continue
        user_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or ("unknown user" if language == "en" else "неизвестный пользователь")
        callback_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or "unknown"
        builder.button(text=html.quote(user_nickname_val), callback_data=f"{command_type}:{user_obj.id}:{callback_nickname_val[:30]}")

    if not builder._markup:
         await message.reply("No other users online to select." if language == "en" else "Нет других пользователей онлайн для выбора.")
         return

    builder.adjust(2)
    command_text_localized_map = {
        "id": ("Select a user to get ID:" if language == "en" else "Выберите пользователя для получения ID:"),
        "kick": ("Select a user to kick:" if language == "en" else "Выберите пользователя для кика:"),
        "ban": ("Select a user to ban:" if language == "en" else "Выберите пользователя для бана:")
    }
    command_text_val = command_text_localized_map.get(command_type, "Select a user:")
    await message.reply(command_text_val, reply_markup=builder.as_markup())

def get_help_text(user_language: str) -> str:
    if user_language == "ru":
        help_text_content = (
            "Этот бот пересылает сообщения с TeamTalk сервера в Telegram и уведомляет о входе/выходе пользователей.\n\n"
            "**Команды Telegram:**\n"
            "/who - Показать онлайн пользователей.\n"
            "/id - Получить ID пользователя (через кнопки).\n"
            "/kick - Кикнуть пользователя с сервера (админ, через кнопки).\n"
            "/ban - Забанить пользователя на сервере (админ, через кнопки).\n"
            "/cl `en|ru` - Изменить язык бота.\n"
            "/notify_all - Включить все уведомления.\n"
            "/notify_join_off - Выключить уведомления о входах.\n"
            "/notify_leave_off - Выключить уведомления о выходах.\n"
            "/notify_none - Выключить все уведомления.\n"
            "/start - Запустить бота или обработать deeplink.\n"
            "/mute user `<username>` - Добавить пользователя в список мьюта (не получать уведомления).\n"
            "/unmute user `<username>` - Удалить пользователя из списка мьюта.\n"
            '/mute_all - Включить режим "мьют всех" (уведомления только для исключений из списка мьюта).\n'
            '/unmute_all - Выключить режим "мьют всех" (уведомления для всех, кроме списка мьюта).\n'
            "/toggle_noon - Включить/выключить тихие уведомления, если связанный пользователь TeamTalk онлайн.\n"
            "/my_noon_status - Проверить статус функции 'не в сети'.\n"
            "/help - Показать это сообщение.\n\n"
            "**Примечание по мьютам и кнопкам 'Переключить статус игнорирования':**\n"
            "- Кнопка 'Переключить статус игнорирования' под сообщениями о входе/выходе управляет вашим персональным списком мьюта для этого пользователя TeamTalk.\n"
            "- Когда `/mute_all` **выключен** (по умолчанию): список мьюта содержит тех, от кого **не** приходят уведомления. Нажатие кнопки переключает, будет ли пользователь в этом списке.\n"
            "- Когда `/mute_all` **включен**: список мьюта содержит тех, от кого **приходят** уведомления (исключения). Нажатие кнопки переключает, будет ли пользователь в этом списке исключений.\n"
            "- `/unmute_all` всегда выключает `/mute_all` и очищает список.\n\n"
            "**Примечание по функции 'не в сети' (/toggle_noon):**\n"
            "- Сначала настройте через TeamTalk: `/not on online` в личные сообщения боту TeamTalk.\n"
            "- После подтверждения по ссылке в Telegram, эта функция будет активна.\n"
            "- Если связанный пользователь TeamTalk онлайн, уведомления в Telegram будут приходить без звука.\n\n"
            "**Команды TeamTalk (в личные сообщения боту):**\n"
            "/sub - Получить ссылку для подписки на уведомления.\n"
            "/unsub - Получить ссылку для отписки от уведомлений.\n"
            "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Добавить админа бота (только для ADMIN_USERNAME из .env).\n"
            "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Удалить админа бота (только для ADMIN_USERNAME из .env).\n"
            "/not on online - Настроить тихие уведомления, когда вы онлайн в TeamTalk.\n"
            "/help - Показать справку."
        )
    else:
        help_text_content = (
            "This bot forwards messages from a TeamTalk server to Telegram and sends join/leave notifications.\n\n"
            "**Telegram Commands:**\n"
            "/who - Show online users.\n"
            "/id - Get ID of a user (via buttons).\n"
            "/kick - Kick a user from the server (admin, via buttons).\n"
            "/ban - Ban a user from the server (admin, via buttons).\n"
            "/cl `en|ru` - Change bot language.\n"
            "/notify_all - Enable all join/leave notifications.\n"
            "/notify_join_off - Disable join notifications.\n"
            "/notify_leave_off - Disable leave notifications.\n"
            "/notify_none - Disable all join/leave notifications.\n"
            "/start - Start bot or process deeplink.\n"
            "/mute user `<username>` - Add user to mute list (don't receive notifications).\n"
            "/unmute user `<username>` - Remove user from mute list.\n"
            "/mute_all - Enable 'mute all' mode (only get notifications for exceptions in the mute list).\n"
            "/unmute_all - Disable 'mute all' mode (get notifications for everyone except the mute list).\n"
            "/toggle_noon - Toggle silent notifications if your linked TeamTalk user is online.\n"
            "/my_noon_status - Check your 'not on online' feature status.\n"
            "/help - Show this help message.\n\n"
            "**Note on Mutes and 'Toggle ignore status' Buttons:**\n"
            "- The 'Toggle ignore status' button under join/leave messages manages your personal mute list for that TeamTalk user.\n"
            "- When `/mute_all` is **disabled** (default): the mute list contains users you **don't** get notifications from. Pressing the button toggles if the user is in this list.\n"
            "- When `/mute_all` is **enabled**: the mute list contains users you **do** get notifications from (exceptions). Pressing the button toggles if the user is in this exception list.\n"
            "- `/unmute_all` always disables `/mute_all` and clears the list.\n\n"
            "**Note on 'Not on Online' feature (/toggle_noon):**\n"
            "- First, set it up via TeamTalk: `/not on online` in a private message to the TeamTalk bot.\n"
            "- After confirming via the link in Telegram, this feature will be active.\n"
            "- If your linked TeamTalk user is online, Telegram notifications will be silent.\n\n"
            "**TeamTalk Commands (in private message to the bot):**\n"
            "/sub - Get a link to subscribe to notifications.\n"
            "/unsub - Get a link to unsubscribe from notifications.\n"
            "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Add bot admin (ADMIN_USERNAME from .env only).\n"
            "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Remove bot admin (ADMIN_USERNAME from .env only).\n"
            "/not on online - Set up silent notifications for when you are online in TeamTalk.\n"
            "/help - Show help."
        )
    return help_text_content

async def send_long_tt_reply(reply_method: Callable, text: str, max_len_bytes: int = 511):
    if not text:
        return

    parts_to_send_list = []
    remaining_text_val = text

    while remaining_text_val:
        if len(remaining_text_val.encode("utf-8")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text_val)
            remaining_text_val = ""
            break

        current_chunk_bytes_val = 0
        possible_split_point_val = -1
        temp_buffer_val = ""

        for i, char_code_val in enumerate(remaining_text_val):
            char_bytes_val = char_code_val.encode("utf-8")

            if current_chunk_bytes_val + len(char_bytes_val) > max_len_bytes:
                if possible_split_point_val > 0 :
                    final_chunk_str_val = temp_buffer_val[:possible_split_point_val]
                    parts_to_send_list.append(final_chunk_str_val)
                    remaining_text_val = temp_buffer_val[possible_split_point_val:].lstrip() + remaining_text_val[i:]
                else:
                    parts_to_send_list.append(temp_buffer_val)
                    remaining_text_val = remaining_text_val[i:]
                break

            temp_buffer_val += char_code_val
            current_chunk_bytes_val += len(char_bytes_val)

            if char_code_val == "\n" or char_code_val == " ":
                possible_split_point_val = len(temp_buffer_val)

            if i == len(remaining_text_val) - 1:
                parts_to_send_list.append(temp_buffer_val)
                remaining_text_val = ""
                break
        else:
            if temp_buffer_val:
                 parts_to_send_list.append(temp_buffer_val)
            remaining_text_val = ""

    for part_idx_val, part_to_send_str_val in enumerate(parts_to_send_list):
        if part_to_send_str_val.strip():
            reply_method(part_to_send_str_val)
            logger.debug(f"Sent part {part_idx_val + 1}/{len(parts_to_send_list)} of help message, length {len(part_to_send_str_val.encode('utf-8'))} bytes.")
            if part_idx_val < len(parts_to_send_list) - 1:
                await asyncio.sleep(0.3)

@catch_all_router.message()
async def handle_unknown_command(message: Message, language: str):
    if not message.text:
        return
    logger.info(f"Received unknown message from {message.from_user.id}: {message.text[:50]}")
    await message.reply("Unknown command. Use /help to see available commands." if language == "en" else "Неизвестная команда. Используйте /help для просмотра доступных команд.")

@tt_bot.event
async def on_ready():
    global current_tt_instance, login_complete_time
    server_info_obj = pytalk.TeamTalkServerInfo(
        config["HOSTNAME"], config["PORT"], config["PORT"],
        config["USERNAME"], config["PASSWORD"], encrypted=config["ENCRYPTED"], nickname=config["NICKNAME"]
    )
    try:
        login_complete_time = None
        await tt_bot.add_server(server_info_obj)
        logger.info(f"Initiated connection process for server: {config['HOSTNAME']}.")
    except Exception as e:
        logger.error(f"Error initiating server connection in on_ready: {e}")
        asyncio.create_task(_reconnect(None))

@tt_bot.event
async def on_my_login(server: PytalkServer) -> None:
    global current_tt_instance, login_complete_time
    tt_instance_val = server.teamtalk_instance
    current_tt_instance = tt_instance_val
    login_complete_time = None
    logger.info(f"Successfully logged in to server: {ttstr(tt_instance_val.server.get_properties().server_name)}")
    try:
        channel_id_or_path_val = config["CHANNEL"]
        channel_id_val = -1
        if channel_id_or_path_val.isdigit():
            channel_id_val = int(channel_id_or_path_val)
        else:
            try:
                channel_obj_val = tt_instance_val.get_channel_from_path(channel_id_or_path_val)
                if channel_obj_val:
                    channel_id_val = channel_obj_val.id
                else:
                    logger.error(f"Channel path '{channel_id_or_path_val}' not found during login.")
            except Exception as path_e:
                 logger.error(f"Error resolving channel path '{channel_id_or_path_val}' during login: {path_e}")

        if channel_id_val != -1:
            logger.info(f"Attempting to join channel: {config['CHANNEL']} (Resolved ID: {channel_id_val})")
            tt_instance_val.join_channel_by_id(channel_id_val, password=config["CHANNEL_PASSWORD"])
            await asyncio.sleep(1)
        else:
            logger.warning(f"Could not resolve channel '{config['CHANNEL']}' to an ID during login. Will attempt later if needed.")

        tt_instance_val.change_status(UserStatusMode.ONLINE, config["STATUS_TEXT"])
        logger.info(f"Status set to: {config['STATUS_TEXT']}")
        login_complete_time = datetime.utcnow()
        logger.info(f"Login sequence complete at {login_complete_time}.")


    except Exception as e:
        logger.error(f"Error during on_my_login (joining channel/setting status): {e}")
        if tt_instance_val:
            asyncio.create_task(_rejoin_channel(tt_instance_val))

async def _reconnect(tt_instance_val: TeamTalkInstance | None):
    global current_tt_instance, login_complete_time
    if current_tt_instance:
        logger.info("Reconnect already in progress or instance exists, skipping new task.")
        return
    logger.info("Starting reconnection process...")
    current_tt_instance = None
    login_complete_time = None
    await asyncio.sleep(5)
    while True:
        try:
            logger.info("Attempting to re-add server via on_ready logic...")
            await on_ready()
            await asyncio.sleep(10)

            if current_tt_instance and current_tt_instance.connected and current_tt_instance.logged_in:
                 logger.info("Reconnection successful.")
                 break
            logger.warning("Reconnection attempt failed (instance not ready/connected/logged in). Retrying in 15 seconds...")
            current_tt_instance = None
            login_complete_time = None

        except Exception as e:
            logger.error(f"Error during reconnection attempt: {e}. Retrying in 15 seconds...")
            current_tt_instance = None
            login_complete_time = None
        await asyncio.sleep(15)

async def _rejoin_channel(tt_instance_val: TeamTalkInstance):
    global login_complete_time
    if tt_instance_val is not current_tt_instance:
        logger.warning("Rejoin channel called for an outdated/inactive instance. Aborting.")
        return

    logger.info("Starting channel rejoin process...")
    await asyncio.sleep(2)
    attempts_val = 0
    max_attempts_val = 3

    while True:
        if not current_tt_instance or not current_tt_instance.connected or not current_tt_instance.logged_in:
             logger.warning("Not connected/logged in during rejoin attempt. Aborting rejoin and ensuring reconnect is triggered.")
             if not current_tt_instance:
                 login_complete_time = None
                 asyncio.create_task(_reconnect(None))
             return

        attempts_val += 1
        try:
            channel_id_or_path_val = config["CHANNEL"]
            channel_id_val = -1
            channel_name_val = ""
            try:
                if channel_id_or_path_val.isdigit():
                    channel_id_val = int(channel_id_or_path_val)
                    channel_obj_val = tt_instance_val.get_channel(channel_id_val)
                    channel_name_val = ttstr(channel_obj_val.name) if channel_obj_val else f"ID {channel_id_val}"
                else:
                    channel_obj_val = tt_instance_val.get_channel_from_path(channel_id_or_path_val)
                    if channel_obj_val:
                        channel_id_val = channel_obj_val.id
                        channel_name_val = ttstr(channel_obj_val.name)
                    else:
                        raise ValueError(f"Channel path '{channel_id_or_path_val}' not found")
            except Exception as chan_e:
                 logger.error(f"Error resolving channel '{channel_id_or_path_val}' during rejoin (Attempt {attempts_val}): {chan_e}. Retrying...")
                 await asyncio.sleep(5)
                 continue

            logger.info(f"Attempting to rejoin channel: {channel_name_val} (ID: {channel_id_val}) (Attempt {attempts_val})")
            tt_instance_val.join_channel_by_id(channel_id_val, password=config["CHANNEL_PASSWORD"])

            await asyncio.sleep(1)
            current_channel_id_val = tt_instance_val.getMyChannelID()
            if current_channel_id_val == channel_id_val:
                logger.info(f"Rejoined channel {channel_name_val} successfully.")
                break
            logger.warning(f"Failed to rejoin channel {channel_name_val}. Current channel ID: {current_channel_id_val}. Retrying...")

        except Exception as e:
            logger.error(f"Error during channel rejoin loop (Attempt {attempts_val}): {e}. Retrying in 3 seconds...")

        if attempts_val >= max_attempts_val:
            logger.warning(f"Failed to rejoin channel after {max_attempts_val} attempts. Waiting 20 seconds before trying again.")
            await asyncio.sleep(20)
            attempts_val = 0
        else:
            await asyncio.sleep(3)

@tt_bot.event
async def on_my_connection_lost(server: PytalkServer) -> None:
    global current_tt_instance, login_complete_time
    logger.warning("Connection lost (possibly kicked from server). Attempting to reconnect...")
    current_tt_instance = None
    login_complete_time = None
    asyncio.create_task(_reconnect(None))

@tt_bot.event
async def on_my_kicked_from_channel(channel_obj: PytalkChannel) -> None:
    global current_tt_instance, login_complete_time
    tt_instance_val = current_tt_instance

    if not tt_instance_val:
        logger.error("Kicked from channel/server, but current_tt_instance is None. Cannot process.")
        login_complete_time = None
        asyncio.create_task(_reconnect(None))
        return

    try:
        channel_id_val = channel_obj.id if channel_obj else -1

        if channel_id_val == 0:
            logger.warning("Kicked from server (received channel ID 0). Attempting to reconnect...")
            current_tt_instance = None
            login_complete_time = None
            asyncio.create_task(_reconnect(None))
        elif channel_id_val > 0:
            channel_name_val = ttstr(channel_obj.name) if channel_obj else "Unknown Channel"
            logger.warning(f"Kicked from channel {channel_name_val} (ID: {channel_id_val}). Attempting to rejoin...")
            asyncio.create_task(_rejoin_channel(tt_instance_val))
        else:
            logger.error(f"Received unexpected kick event with channel_obj ID: {channel_id_val}. Attempting full reconnect.")
            current_tt_instance = None
            login_complete_time = None
            asyncio.create_task(_reconnect(None))

    except Exception as e:
        channel_id_for_log_val = "unknown"
        if "channel_id_val" in locals():
            channel_id_for_log_val = channel_id_val
        logger.error(f"Error handling on_my_kicked_from_channel (ID: {channel_id_for_log_val}): {e}")
        current_tt_instance = None
        login_complete_time = None
        asyncio.create_task(_reconnect(None))

@tt_bot.event
async def on_message(message: TeamTalkMessage) -> None:
    if not current_tt_instance or message.from_id == current_tt_instance.getMyUserID() or message.type != 1:
        return

    sender_username_val = ttstr(message.user.username)
    message_content_val = message.content

    logger.info(f"Received private message from {sender_username_val}: {message_content_val[:100]}")

    async with SessionFactory() as session:
        if message_content_val.startswith("/sub"):
            await handle_tt_subscribe_command(message, session)
        elif message_content_val.startswith("/unsub"):
            await handle_tt_unsubscribe_command(message, session)
        elif message_content_val.startswith("/add_admin"):
            await handle_tt_add_admin_command(message, session)
        elif message_content_val.startswith("/remove_admin"):
            await handle_tt_remove_admin_command(message, session)
        elif message_content_val.strip().lower() == "/not on online":
            await handle_tt_not_on_online_command(message, session)
        elif message_content_val.startswith("/help"):
            admin_lang_val = "en"
            if config["TG_ADMIN_CHAT_ID"]:
                 admin_settings_val = USER_SETTINGS_CACHE.get(int(config["TG_ADMIN_CHAT_ID"]))
                 if admin_settings_val:
                     admin_lang_val = admin_settings_val.get("language", "en")
            await send_help_message_tt(message, admin_lang_val)
        elif message_content_val.startswith("/"):
            reply_text_val = "Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help."
            message.reply(reply_text_val)
            logger.warning(f"Received unknown TT command from {sender_username_val}: {message_content_val}")
        elif config["TG_ADMIN_CHAT_ID"] and tg_bot_message:
            admin_lang_val = "en"
            admin_id_val = int(config["TG_ADMIN_CHAT_ID"])
            admin_settings_val = USER_SETTINGS_CACHE.get(admin_id_val)
            if admin_settings_val:
                admin_lang_val = admin_settings_val.get("language", "en")

            await forward_tt_message_to_telegram(
                message=message,
                server_name_conf=config["SERVER_NAME"],
                sender_nickname=ttstr(message.user.nickname),
                message_text=message_content_val,
                admin_chat_id=admin_id_val,
                admin_language=admin_lang_val,
                tt_instance_for_check=current_tt_instance
            )

async def forward_tt_message_to_telegram(
    message: TeamTalkMessage,
    server_name_conf: str | None,
    sender_nickname: str,
    message_text: str,
    admin_chat_id: int,
    admin_language: str,
    tt_instance_for_check: TeamTalkInstance | None = None
):
    tt_instance_val = message.teamtalk_instance
    server_name_val = "Unknown Server"
    if tt_instance_val and tt_instance_val.connected:
         try:
             server_name_val = server_name_conf or ttstr(tt_instance_val.server.get_properties().server_name)
         except Exception as e:
             logger.error(f"Could not get server name from TT instance: {e}")

    sender_display_val = sender_nickname or ttstr(message.user.username) or "Unknown User"

    text_val = (f"Сообщение с сервера {html.quote(server_name_val)}\nОт {html.quote(sender_display_val)}:\n\n{html.quote(message_text)}" if admin_language == "ru"
            else f"Message from server {html.quote(server_name_val)}\nFrom {html.quote(sender_display_val)}:\n\n{html.quote(message_text)}")

    asyncio.create_task(send_telegram_message(
        config["TG_BOT_MESSAGE_TOKEN"],
        admin_chat_id,
        text_val,
        language=admin_language,
        reply_tt=message.reply,
        tt_instance_for_check=tt_instance_for_check
    ))

async def handle_tt_subscribe_command(message: TeamTalkMessage, session: AsyncSession):
    try:
        token_val = await create_deeplink(session, "subscribe")
        bot_info_val = await tg_bot_event.get_me()
        deeplink_val = f"https://t.me/{bot_info_val.username}?start={token_val}"
        reply_text_val = f"Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_val}"
        message.reply(reply_text_val)
        logger.info(f"Generated subscribe deeplink {token_val} for TT user {ttstr(message.user.username)}")
    except Exception as e:
        logger.error(f"Error processing TT subscription for {ttstr(message.user.username)}: {e}")
        message.reply("An error occurred while processing the subscription request.")

async def handle_tt_unsubscribe_command(message: TeamTalkMessage, session: AsyncSession):
    try:
        token_val = await create_deeplink(session, "unsubscribe")
        bot_info_val = await tg_bot_event.get_me()
        deeplink_val = f"https://t.me/{bot_info_val.username}?start={token_val}"
        reply_text_val = f"Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_val}"
        message.reply(reply_text_val)
        logger.info(f"Generated unsubscribe deeplink {token_val} for TT user {ttstr(message.user.username)}")
    except Exception as e:
        logger.error(f"Error processing TT unsubscription for {ttstr(message.user.username)}: {e}")
        message.reply("An error occurred while processing the unsubscription request.")

async def handle_tt_add_admin_command(message: TeamTalkMessage, session: AsyncSession):
    sender_username_val = ttstr(message.user.username)
    if not config["ADMIN_USERNAME"] or sender_username_val != config["ADMIN_USERNAME"]:
        logger.warning(f"Unauthorized /add_admin attempt by TT user {sender_username_val}.")
        message.reply("You do not have permission to use this command.")
        return

    try:
        parts_list = message.content.split()
        if len(parts_list) < 2:
            message.reply("Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432")
            return

        telegram_ids_to_add_list = parts_list[1:]
        added_count_val = 0
        errors_list = []
        for telegram_id_str_val in telegram_ids_to_add_list:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await add_admin(session, telegram_id_val):
                    added_count_val += 1
                    logger.info(f"Admin {telegram_id_val} added by TT user {sender_username_val}")
                else:
                    errors_list.append(f"ID {telegram_id_val} is already an admin or failed to add.")
            else:
                errors_list.append(f"'{telegram_id_str_val}' is not a valid numeric Telegram ID.")

        reply_parts_list = []
        if added_count_val > 0:
            reply_parts_list.append(f"Successfully added {added_count_val} admin(s).")
        if errors_list:
            reply_parts_list.append("Errors:\n- " + "\n- ".join(errors_list))

        message.reply("\n".join(reply_parts_list) if reply_parts_list else "No valid IDs provided.")

    except Exception as e:
        logger.error(f"Error processing /add_admin command from {sender_username_val}: {e}")
        message.reply("An error occurred while processing the command.")

async def handle_tt_remove_admin_command(message: TeamTalkMessage, session: AsyncSession):
    sender_username_val = ttstr(message.user.username)
    if not config["ADMIN_USERNAME"] or sender_username_val != config["ADMIN_USERNAME"]:
        logger.warning(f"Unauthorized /remove_admin attempt by TT user {sender_username_val}.")
        message.reply("You do not have permission to use this command.")
        return

    try:
        parts_list = message.content.split()
        if len(parts_list) < 2:
            message.reply("Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432")
            return

        telegram_ids_to_remove_list = parts_list[1:]
        removed_count_val = 0
        errors_list = []
        for telegram_id_str_val in telegram_ids_to_remove_list:
            if telegram_id_str_val.isdigit():
                telegram_id_val = int(telegram_id_str_val)
                if await remove_admin_db(session, telegram_id_val):
                    removed_count_val += 1
                    logger.info(f"Admin {telegram_id_val} removed by TT user {sender_username_val}")
                else:
                    errors_list.append(f"Admin with ID {telegram_id_val} not found.")
            else:
                errors_list.append(f"'{telegram_id_str_val}' is not a valid numeric Telegram ID.")

        reply_parts_list = []
        if removed_count_val > 0:
            reply_parts_list.append(f"Successfully removed {removed_count_val} admin(s).")
        if errors_list:
            reply_parts_list.append("Info/Errors:\n- " + "\n- ".join(errors_list))

        message.reply("\n".join(reply_parts_list) if reply_parts_list else "No valid IDs provided.")

    except Exception as e:
        logger.error(f"Error processing /remove_admin command from {sender_username_val}: {e}")
        message.reply("An error occurred while processing the command.")

async def handle_tt_not_on_online_command(message: TeamTalkMessage, session: AsyncSession):
    sender_tt_username = ttstr(message.user.username)

    if message.content.strip().lower() != "/not on online":
        message.reply("Usage: /not on online")
        return

    try:
        token = await create_deeplink(
            session,
            action="confirm_not_on_online",
            payload=sender_tt_username,
            expected_telegram_id=None
        )
        bot_info = await tg_bot_event.get_me()
        deeplink_url = f"https://t.me/{bot_info.username}?start={token}"

        message.reply(f"To enable 'not on online' notifications for your TeamTalk user '{sender_tt_username}', "
                      f"please open this link in Telegram and confirm "
                      f"(link valid for 5 minutes):\n{deeplink_url}")
        logger.info(f"Generated 'not on online' confirmation deeplink {token} for TT user {sender_tt_username} (generic TG target)")
    except Exception as e:
        logger.error(f"Error processing TT /not on online for {sender_tt_username}: {e}")
        message.reply("An error occurred while processing the request.")


async def send_help_message_tt(message: TeamTalkMessage, language: str):
    help_text_val = get_help_text(language)
    await send_long_tt_reply(message.reply, help_text_val, max_len_bytes=511)

async def should_notify(telegram_id: int, user_username: str, event_type: str) -> bool:
    user_settings_val = USER_SETTINGS_CACHE.get(telegram_id)
    if not user_settings_val:
         logger.warning(f"Settings not found in cache for {telegram_id} during should_notify check.")
         return False

    notification_pref_val = user_settings_val.get("notification_settings", NotificationSetting.ALL)
    mute_settings_val = user_settings_val.get("mute_settings", {"muted_users": set(), "mute_all": False})

    if notification_pref_val == NotificationSetting.NONE:
        return False
    if event_type == "join" and notification_pref_val == NotificationSetting.JOIN_OFF:
        return False
    if event_type == "leave" and notification_pref_val == NotificationSetting.LEAVE_OFF:
        return False

    mute_all_val = mute_settings_val.get("mute_all", False)
    muted_users_set = mute_settings_val.get("muted_users", set())

    if mute_all_val:
        return user_username in muted_users_set
    return user_username not in muted_users_set

async def send_join_leave_notification(
    event_type: str,
    user: TeamTalkUser,
    tt_instance: TeamTalkInstance
):
    server_obj = user.server
    server_name_val = config["SERVER_NAME"] or ttstr(tt_instance.server.get_properties().server_name) if tt_instance else "Unknown Server"
    user_nickname_val = ttstr(user.nickname) or ttstr(user.username) or "unknown user"
    user_username_val = ttstr(user.username)
    user_id_val = user.id

    if not user_username_val:
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname_val}, ID: {user_id_val}). Skipping notification.")
        return

    if config["GLOBAL_IGNORE_USERNAME"] and user_username_val == config["GLOBAL_IGNORE_USERNAME"]:
        logger.info(f"User {user_username_val} is globally ignored. Skipping {event_type} notification.")
        return

    async with SessionFactory() as session:
        subscribers_list = await get_all_subscribers(session)

    chat_ids_to_notify_list = []
    for chat_id_val in subscribers_list:
        if chat_id_val not in USER_SETTINGS_CACHE:
            async with SessionFactory() as temp_session:
                 await _async_load_user_settings(chat_id_val, temp_session)

        if await should_notify(chat_id_val, user_username_val, event_type):
            chat_ids_to_notify_list.append(chat_id_val)

    if not chat_ids_to_notify_list:
        logger.info(f"No subscribers to notify for {event_type} of user {user_username_val}.")
        return

    def text_gen(lang_code: str) -> str:
        if event_type == "join":
            return (f"{html.quote(user_nickname_val)} присоединился к серверу {html.quote(server_name_val)}" if lang_code == "ru"
                    else f"User {html.quote(user_nickname_val)} joined server {html.quote(server_name_val)}")
        return (f"{html.quote(user_nickname_val)} покинул сервер {html.quote(server_name_val)}" if lang_code == "ru"
                else f"User {html.quote(user_nickname_val)} left server {html.quote(server_name_val)}")

    def markup_gen(tt_user_username: str, tt_user_nickname: str, lang_code: str, recipient_tg_id: int) -> InlineKeyboardMarkup | None:
        button_display_nickname_val = html.quote(tt_user_nickname[:30])
        callback_data_val = f"toggle_ignore_user:{tt_user_username}:{tt_user_nickname[:30]}"
        button_text_val = (f"Переключить статус игнорирования: {button_display_nickname_val}" if lang_code == "ru"
                        else f"Toggle ignore status: {button_display_nickname_val}")
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_text_val, callback_data=callback_data_val)]
        ])

    async with SessionFactory() as send_session:
        await send_telegram_messages(
            token=config["TG_EVENT_TOKEN"],
            chat_ids=chat_ids_to_notify_list,
            text_generator=text_gen,
            session=send_session,
            reply_markup_generator=markup_gen,
            tt_user_username_for_markup=user_username_val,
            tt_user_nickname_for_markup=user_nickname_val,
            tt_instance_for_check=tt_instance
        )
    logger.info(f"Prepared {event_type} notification for {user_username_val} ({user_id_val}) to {len(chat_ids_to_notify_list)} subscribers.")


@tt_bot.event
async def on_user_login(user: TeamTalkUser) -> None:
    global login_complete_time
    server_obj = user.server
    tt_instance_val = server_obj.teamtalk_instance

    if login_complete_time is None or datetime.utcnow() < login_complete_time + timedelta(seconds=2):
        logger.debug(f"Ignoring potential initial sync join for {ttstr(user.username)} ({user.id}).")
        return
    await send_join_leave_notification("join", user, tt_instance_val)

@tt_bot.event
async def on_user_logout(user: TeamTalkUser) -> None:
    await send_join_leave_notification("leave", user, user.server.teamtalk_instance)

async def set_commands(bot_obj: Bot):
    commands_list = [
        BotCommand(command="who", description="Show online users"),
        BotCommand(command="id", description="Get user ID (buttons)"),
        BotCommand(command="kick", description="Kick user (admin, buttons)"),
        BotCommand(command="ban", description="Ban user (admin, buttons)"),
        BotCommand(command="cl", description="Change language (en/ru)"),
        BotCommand(command="notify_all", description="Enable all join/leave notifications"),
        BotCommand(command="notify_join_off", description="Disable join notifications"),
        BotCommand(command="notify_leave_off", description="Disable leave notifications"),
        BotCommand(command="notify_none", description="Disable all join/leave notifications"),
        BotCommand(command="start", description="Start bot or process deeplink"),
        BotCommand(command="mute", description="Mute notifications from a user (/mute user <name>)"),
        BotCommand(command="unmute", description="Unmute notifications from a user (/unmute user <name>)"),
        BotCommand(command="mute_all", description="Mute all users by default (except exceptions)"),
        BotCommand(command="unmute_all", description="Unmute all users by default (except muted)"),
        BotCommand(command="toggle_noon", description="Toggle 'not on online' silent notifications"),
        BotCommand(command="my_noon_status", description="Check 'not on online' status"),
        BotCommand(command="help", description="Show help message")
    ]
    try:
        await bot_obj.set_my_commands(commands=commands_list, scope=BotCommandScopeAllPrivateChats())
        logger.info("Bot commands updated successfully.")
    except TelegramAPIError as e:
        logger.error(f"Failed to set bot commands: {e}")

async def main():
    await init_db()
    await load_user_settings_to_cache(SessionFactory)
    await set_commands(tg_bot_event)

    dp = Dispatcher()

    dp.update.outer_middleware.register(DbSessionMiddleware(SessionFactory))
    dp.message.middleware(UserSettingsMiddleware())
    dp.callback_query.middleware(UserSettingsMiddleware())
    dp.update.outer_middleware.register(TeamTalkInstanceMiddleware(tt_bot))


    dp.include_router(user_commands_router)
    dp.include_router(settings_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(catch_all_router)

    logger.info("Starting Telegram bot polling and TeamTalk bot...")

    await tt_bot._async_setup_hook()

    try:
        await asyncio.gather(
            dp.start_polling(tg_bot_event, allowed_updates=dp.resolve_used_update_types()),
            tt_bot._start()
        )
    finally:
        logger.info("Shutting down bots...")
        await tg_bot_event.session.close()
        if tg_bot_message:
             await tg_bot_message.session.close()

        logger.info("Disconnecting TeamTalk instances...")
        for tt_instance_item in tt_bot.teamtalks:
            try:
                if tt_instance_item.logged_in:
                    tt_instance_item.logout()
                if tt_instance_item.connected:
                    tt_instance_item.disconnect()
                tt_instance_item.closeTeamTalk()
                logger.info(f"Closed TeamTalk instance for {tt_instance_item.server_info.host}")
            except Exception as e:
                logger.error(f"Error closing TeamTalk instance for {tt_instance_item.server_info.host}: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ValueError, KeyError) as ve:
        logger.critical(f"Configuration Error: {ve}. Please check your .env file or environment variables.")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred in main: {e}", exc_info=True)
    finally:
        logger.info("Application finished.")
