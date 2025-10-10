# TeamTalk Telegram Sender (TTTM)

Repository: [https://github.com/kirill-jjj/teamtalk-telegram-sender/](https://github.com/kirill-jjj/teamtalk-telegram-sender/)

[Русская версия README (Readme.md)](Readme.md)

**Note:** A significant portion of this bot's code (approximately 80%) was generated with the assistance of Artificial Intelligence. While the code has been tested and is in a working or near-working state, some parts may not be optimal or entirely human-readable. You might encounter AI-generated comments like `# changed here` or similar, left during the development and debugging process.

**Acknowledgments:**

*   Special thanks to **[BlindMaster24](https://github.com/BlindMaster24)**, the current active developer and maintainer of the excellent [py-talk-ex](https://github.com/BlindMaster24/pytalk) library, for laying the groundwork and initial idea for this bot, without which further development (including AI-assisted) would have been challenging.
*   Thanks to **[gumerov-amir](https://github.com/gumerov-amir)**, developer of TTMediaBot and other projects, for assistance with fixing the `/help` command after a major AI-driven refactoring effort (in the now-deleted `ai-refactor` branch).
*   Gratitude to **[a11cf0](https://github.com/a11cf0)** for numerous fixes during the very early stages of development when the bot was only capable of forwarding messages to the administrator.

---

This bot acts as a bridge between a TeamTalk 5 server and Telegram. It monitors user login and logout events on the TeamTalk server and sends notifications to Telegram. It can also forward private messages addressed to the bot in TeamTalk to an administrator in Telegram.

## Core Features

*   **Join/Leave Notifications:** Sends messages to Telegram when a user connects to or disconnects from the TeamTalk server.
*   **Private Message Forwarding:** Private messages sent to the bot in TeamTalk can be forwarded to a specified Telegram administrator.
*   **Interactive Settings via Telegram:**
    *   `/settings`: Provides access to a comprehensive menu for managing interface language, notification subscription preferences (all, join-only, leave-only, or none), user block/allow lists (Mute lists), and the "Not on Online" (NOON) feature.
*   **View Online Users:**
    *   `/who`: Shows the list of users currently online on the TeamTalk server.
*   **TeamTalk User Administration (for Telegram Admins):**
    *   `/kick`: Initiates the process of kicking a user from the TeamTalk server (user selection via interactive buttons).
    *   `/ban`: Initiates the process of banning a user from the TeamTalk server (user selection via interactive buttons).
*   **"Not on Online" (NOON) Feature:**
    *   Activated by using the `/sub` command in a private message to the bot on the TeamTalk server, which links your TeamTalk account to Telegram.
    *   If the NOON feature is enabled in Telegram settings (`/settings`) and the linked TeamTalk user is online, notifications from the bot to Telegram will be delivered silently.
*   **Management Commands via TeamTalk (in private messages to the bot):**
    *   `/sub`: Sends the user a deeplink to subscribe to Telegram notifications and to link their TeamTalk account for the NOON feature.
    *   `/unsub`: Sends the user a deeplink to unsubscribe from Telegram notifications.
    *   `/add_admin <Telegram ID>`: Allows the main administrator (specified in the configuration) to add other bot administrators in Telegram.
    *   `/remove_admin <Telegram ID>`: Allows the main administrator to remove bot administrators in Telegram.
    *   `/help`: Displays help information for available TeamTalk commands.
*   **Multilingual Support:** Supports English and Russian interface languages in Telegram.
*   **Getting Help:**
    *   `/help`: Displays a help message with a list of available commands and their descriptions in Telegram.

## Technology Stack

*   **Python 3.11+**
*   **[Aiogram 3](https://github.com/aiogram/aiogram)**: An asynchronous framework for the Telegram Bot API.
*   **[Dishka](https://github.com/ishadbol/dishka)**: A fast and flexible Dependency Injection framework.
*   **[py-talk-ex](https://github.com/BlindMaster24/pytalk)**: A library for interacting with the TeamTalk 5 SDK.
*   **[SQLModel](https://sqlmodel.tiangolo.com/)**: An ORM for database interaction, built on Pydantic and SQLAlchemy.
*   **[Alembic](https://alembic.sqlalchemy.org/en/latest/)**: A database migration tool for SQLAlchemy.
*   **[Pydantic](https://docs.pydantic.dev/)**: Used for parsing and validating configuration from `config.toml`.

## Architecture

The project is built on modern asynchronous patterns with an emphasis on modularity, testability, and Separation of Concerns.

*   **Dependency Injection (DI)**: This is the central architectural pattern. Dependencies (e.g., database sessions, repositories, services) are managed by the **Dishka** library and are automatically injected into handlers and services. This eliminates the need for global objects and makes the code cleaner and more testable.

*   **Layered Architecture**: The code is clearly divided into layers:
    *   **Handlers (`bot/telegram_bot/handlers`)**: Receive incoming updates from Telegram and invoke the appropriate business logic.
    *   **Services (`bot/services`)**: Contain the core business logic of the application (e.g., user management, moderation).
    *   **Repositories (`bot/database/repositories`)**: Abstract data access, providing an interface for working with database models (e.g., `UserRepository`).
    *   **Unit of Work (UoW)**: Ensures the atomicity of database operations.

*   **Event-Driven Model**: An `EventBus` is used for loose coupling between components. Components that interact with TeamTalk publish domain events (e.g., `UserJoinedEvent`), and other parts of the system (like the Telegram notifier) subscribe to these events and react accordingly. This allows the `teamtalk_bot` and `telegram_bot` components to be independent of each other.

A more detailed description of the architecture and contribution guidelines can be found in the [AGENTS.md](AGENTS.md) file.

## Installation and Setup

1.  **Install `uv`**: This project uses `uv` for package and virtual environment management. Follow the official `uv` installation guide: [https://github.com/astral-sh/uv#installation](https://github.com/astral-sh/uv#installation)
2.  **Clone the repository**:
    ```bash
    git clone https://github.com/kirill-jjj/teamtalk-telegram-sender.git
    cd teamtalk-telegram-sender
    ```
3.  **Install dependencies**: `uv sync` will automatically create a virtual environment in a `.venv` folder if one doesn't exist and install all required packages. For development, you also need to install the extra dependencies:
    ```bash
    # This command installs both production and development dependencies
    uv sync --all-extras
    ```
4.  **Configure the application**: Copy the `config.example.toml` file to a new file named `config.toml` and fill it with your actual data (API tokens, admin IDs, TeamTalk connection details, etc.).
    ```bash
    cp config.example.toml config.toml
    # Now edit config.toml with your values
    ```
5.  **Apply database migrations**:
    Before the first run or after updating the database models, apply migrations:
    ```bash
    uv run migrate upgrade head
    ```
6.  **Run the bot**:
    ```bash
    uv run start
    ```
    By default, the bot will use the `config.toml` file. You can also specify a different configuration file via the `APP_CONFIG_FILE` environment variable:
    ```bash
    APP_CONFIG_FILE=prod.toml uv run start
    ```

## Database Migrations

This project uses **Alembic** to manage database schema changes.

### When to Use Migrations

*   **Initial Setup**: Before running the bot for the first time, the initial migration must be applied to create the database tables.
*   **After Model Updates**: If you change the SQLModel models in `bot/models.py` (e.g., add a new table or column), you will need to create and apply a new migration.

### Basic Alembic Commands

Migrations are managed using the `uv run migrate` command, which is a wrapper for `alembic`. The `run_alembic.py` script automatically picks up the configuration from `config.toml` (or the file specified in `APP_CONFIG_FILE`).

*   **Apply Migrations**:
    To apply all pending migrations to the database:
    ```bash
    uv run migrate upgrade head
    ```

*   **Create a New Revision (Migration)**:
    After modifying models in `bot/models.py`, use the following command to create a revision:
    ```bash
    uv run migrate revision -m "short_description_of_changes" --autogenerate
    ```
    This command will create a new migration file in `alembic/versions/`. It is crucial to **review** this file and make manual adjustments if necessary, as autogeneration is not always perfect.

*   **Rollback Migrations**:
    To revert the last applied migration:
    ```bash
    uv run migrate downgrade -1
    ```

*   **View Migration History**:
    Shows a list of all migrations and their status.
    ```bash
    uv run migrate history
    ```

## Usage

### Telegram Commands

After starting the bot and completing the initial setup (it is recommended to initiate subscription via the `/sub` command in a private message to the bot in TeamTalk), you can use the following commands in your chat with the bot in Telegram:

*   `/start`: Begins interaction with the bot. Also used to process deeplink URLs (e.g., for confirming subscriptions or unsubscriptions).
*   `/who`: Show the list of users currently online on the TeamTalk server.
*   `/settings`: Open the interactive menu to configure language, notification subscription preferences, manage block/allow lists, and the "Not on Online" (NOON) feature.
*   `/help`: Display the help message with a list of available commands and their descriptions.

**Commands for Telegram Administrators:**

*   `/kick`: Initiate kicking a user from the TeamTalk server (selection via buttons).
*   `/ban`: Initiate banning a user from the TeamTalk server (selection via buttons).

### TeamTalk Commands (in private messages to the bot)

*   `/sub`: Get a link to subscribe to Telegram notifications. This process also links your TeamTalk account for the "Not on Online" (NOON) feature.
*   `/unsub`: Get a link to unsubscribe from notifications. This will remove your subscription and all associated data and settings.
*   `/add_admin <Telegram_ID_1> <Telegram_ID_2> ...`: (Only for the main administrator specified in the configuration) Add Telegram bot administrators.
*   `/remove_admin <Telegram_ID_1> <Telegram_ID_2> ...`: (Only for the main administrator specified in the configuration) Remove Telegram bot administrators.
*   `/help`: Show help for available TeamTalk commands.

Any other text message sent to the bot in a TeamTalk PM will be forwarded to the Telegram administrator (if `TG_ADMIN_CHAT_ID` is specified in the configuration).

## "Not on Online" (NOON) Feature Setup

The "Not on Online" (NOON) feature allows Telegram notifications from this bot to be delivered silently if your linked TeamTalk user is currently online. This helps reduce notification noise if you are actively using TeamTalk.

**Activating and Managing the NOON Feature:**
1.  **Link Account:** Send the `/sub` command to the bot in a private message on the TeamTalk server. The bot will reply with a deeplink.
2.  **Confirm in Telegram:** Open this link in Telegram and press "Start." This action will subscribe you to notifications and link your TeamTalk account for the NOON feature.
3.  **Manage NOON:** After linking, the NOON feature (enabling/disabling) is managed via the `/settings` menu in Telegram.

If the NOON feature is enabled and your linked TeamTalk account is online on the server, notifications from the bot to Telegram will be delivered silently.

## Contributing

Suggestions for improvements and bug reports are welcome! Please create Issues or Pull Requests in the repository.

### Working with Translations

This project uses a gettext-based workflow for handling translations, orchestrated with the `uv run i18n` command and Babel. The localization files are located in the `locales` directory.

1.  **Update Language Catalogs (.po files)**:
    When you add or change any user-facing strings in the Python code that should be translatable (i.e., strings wrapped in `_()`), you need to update the message template file (`locales/messages.pot`) and the language-specific `.po` files for each supported language. The `uv run i18n update` command (which calls `manage_locales.py`) dynamically detects languages by looking for subdirectories in `locales/`.
    ```bash
    uv run i18n update
    ```
    This command first extracts translatable strings from the codebase (as configured in `babel.cfg`) into `locales/messages.pot`, and then merges new strings from `messages.pot` into each `<lang_code>/LC_MESSAGES/messages.po` file. New strings will be added, and changed strings will be marked as "fuzzy" for review. If you've created a new language directory (e.g., `locales/de/LC_MESSAGES/`), this command will also initialize its `messages.po` file based on the template.

3.  **Translate**:
    Edit the `.po` files (e.g., `locales/ru/LC_MESSAGES/messages.po`) using your preferred PO editor (like Poedit, OmegaT) or a text editor. For each `msgid` (source string), provide the translation in the `msgstr` field. For entries marked `#, fuzzy`, review the translation against the new `msgid`, correct it if necessary, and then remove the `#, fuzzy` comment.

4.  **Compile Translations (.mo files)**:
    After translating, compile the `.po` files into binary `.mo` files, which are used by the application at runtime.
    ```bash
    uv run i18n compile
    ```
    This command will place `.mo` files in the appropriate `LC_MESSAGES` directory for each language (e.g., `locales/ru/LC_MESSAGES/messages.mo`). The bot will then be able to use these compiled translations based on user language preferences.

**Adding a New Language (e.g., German 'de'):**
1.  Create the directory structure: `mkdir -p locales/de/LC_MESSAGES/`
2.  Run `uv run i18n update`. The command should find 'de' and initialize `locales/de/LC_MESSAGES/messages.po`.
3.  Translate the new `.po` file.
4.  Run `uv run i18n compile` to compile it.
5.  Ensure the language code 'de' is one that users can select in the bot's settings.

## License

This project is licensed under the **GNU General Public License v3.0**.
The full text of the license can be found in the `LICENSE` file in the root of the repository or at [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html).