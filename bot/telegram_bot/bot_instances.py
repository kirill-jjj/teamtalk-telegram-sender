from aiogram import Bot
from bot.config import app_config

tg_bot_event = Bot(token=app_config["TG_EVENT_TOKEN"])

tg_bot_message = Bot(token=app_config["TG_BOT_MESSAGE_TOKEN"]) if app_config["TG_BOT_MESSAGE_TOKEN"] else None
