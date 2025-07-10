"""A simple script to test loading the bot's configuration from a TOML file."""

from pathlib import Path
import sys

from bot.config import Settings

if __name__ == "__main__":
    config_path = "config.example.toml"
    print(f"Attempting to load configuration from: {config_path}")  # noqa: T201
    try:
        # Add project root to sys.path to allow 'from bot.config import Settings'
        # This simulates how the application might run if 'bot' is in PYTHONPATH
        project_root = Path(__file__).resolve().parent
        sys.path.insert(0, str(project_root))

        settings = Settings.from_toml(config_path)
        print("Configuration loaded successfully!")  # noqa: T201
        print(f"Database file from config: {settings.database.db_file}")  # noqa: T201
        print(f"Telegram event token from config: {settings.telegram.event_token}")  # noqa: T201
        print(f"Default language: {settings.general.default_lang}")  # noqa: T201
        sys.exit(0)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)  # noqa: T201
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
