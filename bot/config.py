import os
import sys
from typing import Any
from dotenv import load_dotenv
from bot.constants import (
    DEFAULT_TT_PORT,
    DEFAULT_TT_STATUS_TEXT,
    DEFAULT_TT_CLIENT_NAME,
    DEFAULT_DATABASE_FILE,
    MIN_ARGS_FOR_ENV_PATH,
    DEFAULT_LANGUAGE as FALLBACK_DEFAULT_LANGUAGE
)

def load_app_config(env_path: str | None = None) -> dict[str, Any]:
    load_dotenv(dotenv_path=env_path)
    config_data = {
        "TG_BOT_TOKEN": os.getenv("TG_BOT_TOKEN"),
        "TG_EVENT_TOKEN": os.getenv("TELEGRAM_BOT_EVENT_TOKEN") or os.getenv("TG_BOT_TOKEN"),
        "TG_BOT_MESSAGE_TOKEN": os.getenv("TG_BOT_MESSAGE_TOKEN"),
        "TG_ADMIN_CHAT_ID": os.getenv("TG_ADMIN_CHAT_ID"),
        "HOSTNAME": os.getenv("HOST_NAME"),
        "PORT": int(os.getenv("PORT", str(DEFAULT_TT_PORT))),
        "ENCRYPTED": os.getenv("ENCRYPTED") == "1",
        "USERNAME": os.getenv("USER_NAME"),
        "PASSWORD": os.getenv("PASSWORD"),
        "CHANNEL": os.getenv("CHANNEL"),
        "CHANNEL_PASSWORD": os.getenv("CHANNEL_PASSWORD"),
        "NICKNAME": os.getenv("NICK_NAME"),
        "STATUS_TEXT": os.getenv("STATUS_TEXT", DEFAULT_TT_STATUS_TEXT),
        "CLIENT_NAME": os.getenv("CLIENT_NAME") or DEFAULT_TT_CLIENT_NAME,
        "SERVER_NAME": os.getenv("SERVER_NAME"),
        "ADMIN_USERNAME": os.getenv("ADMIN"),
        "GLOBAL_IGNORE_USERNAMES": os.getenv("GLOBAL_IGNORE_USERNAMES"),
        "DATABASE_FILE": os.getenv("DATABASE_FILE", DEFAULT_DATABASE_FILE),
        "DEFAULT_LANG": os.getenv("DEFAULT_LANG", FALLBACK_DEFAULT_LANGUAGE),
        "GENDER": os.getenv("GENDER", "neutral").lower(),
    }

    # Validate and set effective default language
    raw_default_lang = config_data.get("DEFAULT_LANG", FALLBACK_DEFAULT_LANGUAGE)
    if isinstance(raw_default_lang, str) and raw_default_lang.lower() in ["en", "ru"]:
        config_data["EFFECTIVE_DEFAULT_LANG"] = raw_default_lang.lower()
    else:
        print(f"WARNING: Invalid DEFAULT_LANG value '{raw_default_lang}'. Defaulting to '{FALLBACK_DEFAULT_LANGUAGE}'.", file=sys.stderr)
        config_data["EFFECTIVE_DEFAULT_LANG"] = FALLBACK_DEFAULT_LANGUAGE

    # Validate GENDER
    allowed_genders = ["male", "female", "neutral"]
    if config_data["GENDER"] not in allowed_genders:
        print(f"WARNING: Invalid GENDER value '{config_data['GENDER']}'. Must be one of {allowed_genders}. Defaulting to 'neutral'.", file=sys.stderr)
        config_data["GENDER"] = "neutral"

    if not config_data["TG_EVENT_TOKEN"] and not config_data["TG_BOT_TOKEN"]:
        raise ValueError("Missing required environment variable: TG_BOT_TOKEN or TELEGRAM_BOT_EVENT_TOKEN. Check .env file.")
    if not config_data["HOSTNAME"] or not config_data["USERNAME"] or not config_data["PASSWORD"] or not config_data["CHANNEL"] or not config_data["NICKNAME"]:
        raise ValueError("Missing other required TeamTalk environment variables (HOST_NAME, USER_NAME, PASSWORD, CHANNEL, NICK_NAME). Check .env file.")
    if config_data["TG_ADMIN_CHAT_ID"]:
        try:
            config_data["TG_ADMIN_CHAT_ID"] = int(config_data["TG_ADMIN_CHAT_ID"])
        except ValueError:
            raise ValueError("TG_ADMIN_CHAT_ID must be a valid integer.")
    return config_data

app_config = load_app_config(sys.argv[1] if len(sys.argv) >= MIN_ARGS_FOR_ENV_PATH else None)
