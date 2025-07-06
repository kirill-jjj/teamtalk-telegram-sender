import sys
from pathlib import Path

from bot.config import Settings

if __name__ == "__main__":
    config_path = "config.example.toml"
    print(f"Attempting to load configuration from: {config_path}")
    try:
        # Add project root to sys.path to allow 'from bot.config import Settings'
        # This simulates how the application might run if 'bot' is in PYTHONPATH
        project_root = Path(__file__).resolve().parent
        sys.path.insert(0, str(project_root)) # Add project root

        settings = Settings.from_toml(config_path)
        print("Configuration loaded successfully!")
        print(f"Database file from config: {settings.database.db_file}")
        print(f"Telegram event token from config: {settings.telegram.event_token}")
        print(f"Default language: {settings.general.default_lang}")
        sys.exit(0)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
