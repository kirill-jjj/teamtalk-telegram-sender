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

*   Python 3.11+
*   [aiogram](https://github.com/aiogram/aiogram) (asynchronous framework for the Telegram Bot API)
*   [py-talk-ex](https://github.com/BlindMaster24/pytalk) (library for interacting with the TeamTalk 5 SDK)
*   SQLAlchemy (ORM for database interaction)
*   Aiosqlite (asynchronous SQLite driver)
*   python-dotenv (management of environment variables)

## Installation and Setup

1.  **Install `uv` (if not already installed):**
    *   **For Linux and macOS:**
        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
        ```
    *   **For Windows:** The simplest way if you have Python and pip installed is to run `pip install uv`. Other installation methods (e.g., via an installer) can be found on the [official Astral website](https://astral.sh/uv#installation).

2.  **Clone the repository:**
    ```bash
    git clone https://github.com/kirill-jjj/teamtalk-telegram-sender.git
    cd teamtalk-telegram-sender
    ```

3.  **Install dependencies (the `uv sync` command will automatically create a virtual environment in a `.venv` folder if it doesn't exist and install all necessary packages into it):**
    ```bash
    uv sync
    ```
    *(This command prepares the environment with all dependencies.)*
    (Activate the virtual environment: `source .venv/bin/activate` on Linux/macOS or `.venv\Scripts\activate` on Windows)
4.  **Generate Localization Files**: The project uses a gettext-based localization system managed by SCons. These commands should be run from the root of the project.
    *   To extract all translatable strings from the code into a template file (`bot/locales/messages.pot`):
        ```bash
        uv run scons extract
        ```
    *   To create or update language-specific `.po` files (e.g., for Russian `ru` located in `bot/locales/ru/LC_MESSAGES/messages.po`):
        ```bash
        uv run scons update
        ```
        (SCons will dynamically find languages based on subdirectories in `bot/locales/`. If adding a new language, e.g., 'de', first create `bot/locales/de/LC_MESSAGES/` then run this command.)
    *   To compile `.po` files into binary `.mo` files used by the bot at runtime:
        ```bash
        uv run scons
        ```
    (Typically, after initial setup, developers will run `uv run scons extract` when new text is added, then `uv run scons update`, then translate, then `uv run scons` to compile.)
5.  **Configure environment variables**: Copy the `.env.example` file to `.env` and fill in your actual configuration values (API tokens, admin IDs, etc.).
    ```bash
    cp .env.example .env
    # Now edit .env with your values
    ```
6.  **Run the bot**:
    ```bash
    uv run sender.py
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

This project uses a gettext-based workflow for handling translations, orchestrated with SCons and Babel. The localization files are located in the `bot/locales` directory.

1.  **Extract Translatable Strings**:
    When you add or change any user-facing strings in the Python code that should be translatable (i.e., strings wrapped in `_()`), you need to update the message template file (`messages.pot`).
    ```bash
    uv run scons extract
    ```
    This command scans the codebase (as configured in `babel.cfg`) and updates `bot/locales/messages.pot`.

2.  **Update Language Catalogs (.po files)**:
    After the `.pot` template is updated, update the language-specific `.po` files for each supported language. SCons dynamically detects languages by looking for subdirectories in `bot/locales/`.
    ```bash
    uv run scons update
    ```
    This merges new strings from `messages.pot` into each `<lang_code>/LC_MESSAGES/messages.po` file. New strings will be added, and changed strings will be marked as "fuzzy" for review. If you've created a new language directory (e.g., `bot/locales/de/LC_MESSAGES/`), this command will also initialize its `messages.po` file based on the template.

3.  **Translate**:
    Edit the `.po` files (e.g., `bot/locales/ru/LC_MESSAGES/messages.po`) using your preferred PO editor (like Poedit, OmegaT) or a text editor. For each `msgid` (source string), provide the translation in the `msgstr` field. For entries marked `#, fuzzy`, review the translation against the new `msgid`, correct it if necessary, and then remove the `#, fuzzy` comment.

4.  **Compile Translations (.mo files)**:
    After translating, compile the `.po` files into binary `.mo` files, which are used by the application at runtime.
    ```bash
    uv run scons
    ```
    This is the default SCons target and will place `.mo` files in the appropriate `LC_MESSAGES` directory for each language (e.g., `bot/locales/ru/LC_MESSAGES/messages.mo`). The bot will then be able to use these compiled translations based on user language preferences.

**Adding a New Language (e.g., German 'de'):**
1.  Create the directory structure: `mkdir -p bot/locales/de/LC_MESSAGES/`
2.  Run `uv run scons update`. SCons (due to dynamic language detection in `SConstruct`) should find 'de' and initialize `bot/locales/de/LC_MESSAGES/messages.po`.
3.  Translate the new `.po` file.
4.  Run `uv run scons` to compile it.
5.  Ensure the language code 'de' is one that users can select in the bot's settings.

## License

This project is licensed under the **GNU General Public License v3.0**.
The full text of the license can be found in the `LICENSE` file in the root of the repository or at [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html).