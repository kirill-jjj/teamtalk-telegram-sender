# TeamTalk Telegram Sender (TTTM)

Repository: [https://github.com/kirill-jjj/teamtalk-telegram-sender/](https://github.com/kirill-jjj/teamtalk-telegram-sender/)

[Русская версия README (README.md)](README.md)

**Note:** A significant portion of this bot's code (approximately 80%) was generated with the assistance of Artificial Intelligence. While the code has been tested and is in a working or near-working state, some parts may not be optimal or entirely human-readable. You might encounter AI-generated comments like `# changed here` or similar, left during the development and debugging process.

**Acknowledgments:**

*   Special thanks to **[BlindMaster24](https://github.com/BlindMaster24)**, the current active developer and maintainer of the excellent [py-talk-ex](https://github.com/BlindMaster24/pytalk) library, for laying the groundwork and initial idea for this bot, without which further development (including AI-assisted) would have been challenging.
*   Thanks to **[gumerov-amir](https://github.com/gumerov-amir)**, developer of TTMediaBot and other projects, for assistance with fixing the `/help` command after a major AI-driven refactoring effort (in the now-deleted `ai-refactor` branch).
*   Gratitude to **[a11cf0](https://github.com/a11cf0)** for numerous fixes during the very early stages of development when the bot was only capable of forwarding messages to the administrator.

---

This bot acts as a bridge between a TeamTalk 5 server and Telegram. It monitors user login and logout events on the TeamTalk server and sends notifications to Telegram. It can also forward private messages addressed to the bot in TeamTalk to an administrator in Telegram.

## Core Features

*   **Login/Logout Notifications:** Sends messages to Telegram when a user connects to or disconnects from the TeamTalk server.
*   **Private Message Forwarding:** Private messages sent to the bot in TeamTalk can be forwarded to a specified Telegram administrator.
*   **Customizable Notifications:** Telegram users can configure which notifications they want to receive (all, join-only, leave-only, or none).
*   **User Ignoring:** Ability to add specific TeamTalk users to an ignore list to avoid receiving notifications from them.
*   **"Mute All" Mode:** Allows receiving notifications only from selected TeamTalk users (exception list).
*   **"Not on Online" (NOON) Feature:** If a TeamTalk user linked to a Telegram account is online, notifications to Telegram will be delivered silently. This is configured via TeamTalk.
*   **Telegram Commands:**
    *   `/who`: Show the list of online users on the TeamTalk server.
    *   `/id`: Get the TeamTalk User ID of a user (via buttons).
    *   `/kick`, `/ban` (administrators only): Kick or ban a user from the TeamTalk server (via buttons).
    *   `/cl`: Change the bot's interface language (supports Russian and English).
    *   Commands to manage notification settings and ignore lists.
*   **TeamTalk Commands (in private messages to the bot):**
    *   `/sub`: Get a link to subscribe to Telegram notifications.
    *   `/unsub`: Get a link to unsubscribe from notifications.
    *   `/add_admin`, `/remove_admin` (TeamTalk super-administrator only): Manage the bot's Telegram administrators.
    *   `/not on online`: Configure the "Not on Online" feature.
*   **Multilingual:** Support for Russian and English languages.

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

4.  **Configure environment variables:**
    Copy the `.env.example` file to a new file named `.env`:
    ```bash
    cp .env.example .env
    ```
    Then, open the `.env` file in a text editor and fill it with your actual data (tokens, server addresses, credentials, etc.), following the comments within the file. **Never commit your `.env` file to version control (Git).**

5.  **Run the bot (using `uv run` to automatically use and sync the correct environment):**
    ```bash
    uv run python sender.py
    ```
    If you want to specify a path to an `.env` file different from the current directory:
    ```bash
    uv run python sender.py /path/to/your/.env
    ```

## Usage

### Telegram Commands

After starting the bot and completing initial setup (it's recommended to subscribe to notifications using the `/sub` command in a private message to the bot in TeamTalk), you can use the following commands in your Telegram chat with the bot:

*   `/start`: Begin interaction with the bot, process deeplink URLs.
*   `/who`: Show the list of online users on the TeamTalk server.
*   `/id`: Get the TeamTalk User ID of a specified user (selection via buttons).
*   `/help`: Display this help message.
*   `/cl en` or `/cl ru`: Change the bot's language.
*   `/notify_all`: Enable all join/leave notifications.
*   `/notify_join_off`: Disable join notifications.
*   `/notify_leave_off`: Disable leave notifications.
*   `/notify_none`: Disable all notifications.
*   `/mute user <TeamTalk_username>`: Add a TeamTalk user to the ignore list (do not receive notifications from them).
*   `/unmute user <TeamTalk_username>`: Remove a user from the ignore list.
*   `/mute_all`: Enable "Mute All" mode. Notifications will only come from users on the ignore list (which acts as an allow-list in this mode).
*   `/unmute_all`: Disable "Mute All" mode. Notifications will come from everyone except those on the ignore list.
*   `/toggle_noon`: Toggle the "Not on Online" feature.
*   `/my_noon_status`: Check your "Not on Online" feature status.
*   `/kick` (Telegram administrators only): Kick a TeamTalk user (selection via buttons).
*   `/ban` (Telegram administrators only): Ban a TeamTalk user (selection via buttons).

### TeamTalk Commands (in private messages to the bot)

*   `/sub`: Get a link to subscribe to Telegram notifications.
*   `/unsub`: Get a link to unsubscribe from notifications.
*   `/add_admin <Telegram_ID_1> <Telegram_ID_2> ...`: (Only for `ADMIN_USERNAME` from `.env`) Add Telegram bot administrators.
*   `/remove_admin <Telegram_ID_1> <Telegram_ID_2> ...`: (Only for `ADMIN_USERNAME` from `.env`) Remove Telegram bot administrators.
*   `/not on online`: Set up the "Not on Online" feature (for silent Telegram notifications when you are online in TeamTalk).
*   `/help`: Show help for TeamTalk commands.

Any other text message sent to the bot in a TeamTalk PM will be forwarded to `TG_ADMIN_CHAT_ID` if specified.

## "Not on Online" (NOON) Feature Setup

1.  Send the `/not on online` command to the bot in a private message in TeamTalk.
2.  The bot will reply in TeamTalk with a link.
3.  Open this link. It should lead to your Telegram bot with a `start` parameter.
4.  Press "Start" in Telegram. The bot will confirm the setup.
5.  You can now use the `/toggle_noon` command in Telegram to enable/disable this feature. If the feature is enabled and your TeamTalk account (linked during NOON setup) is online on the server, notifications from the bot to Telegram will be delivered silently.

## Contributing

Suggestions for improvements and bug reports are welcome! Please create Issues or Pull Requests in the repository.

## License

This project is licensed under the **GNU General Public License v3.0**.
The full text of the license can be found in the `LICENSE` file in the root of the repository or at [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html).