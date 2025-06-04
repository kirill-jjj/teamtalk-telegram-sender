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

*   **Login/Logout Notifications:** Sends messages to Telegram when a user connects to or disconnects from the TeamTalk server.
*   **Private Message Forwarding:** Private messages sent to the bot in TeamTalk can be forwarded to a specified Telegram administrator.
*   **Customizable Notifications:** Telegram users can configure their notification subscription preferences (all, join-only, leave-only, or none) via the interactive `/settings` menu.
*   **User Ignoring and "Mute All" Mode:** Ability to manage ignored/allowed user lists and "Mute All" mode through the `/settings` menu.
*   **"Not on Online" (NOON) Feature:** If your linked TeamTalk user is online, notifications to Telegram can be delivered silently. This link can be established via the `/sub` or `/not on online` commands in TeamTalk. This feature is also configurable in the `/settings` menu.
*   **Telegram Commands:**
    *   `/who`: Show the list of online users on the TeamTalk server.
    *   `/id`: Get the TeamTalk User ID of a user (via buttons).
    *   `/kick`, `/ban` (administrators only): Kick or ban a user from the TeamTalk server (via buttons).
    *   `/cl`: Change the bot's interface language (supports Russian and English).
    *   `/settings`: Open the interactive menu to configure language, subscription preferences, "Not on Online" (NOON) feature, and manage muted/allowed user lists.
    *   `/mute user <TeamTalk_username>`, `/unmute user <TeamTalk_username>`, `/mute_all`, `/unmute_all`: Quick commands for managing mute lists. Full management is available in the `/settings` menu.
    *   `/toggle_noon`, `/my_noon_status`: Quick commands for the NOON feature. Full management is available in the `/settings` menu.
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
*   `/settings`: Open the interactive menu to configure language, subscription preferences (formerly `/notify_*` commands), "Not on Online" (NOON) feature, and manage muted/allowed user lists.
*   `/mute user <TeamTalk_username>`: Quick command to add a TeamTalk user to the mute list. Full management of mute lists is available in the `/settings` menu.
*   `/unmute user <TeamTalk_username>`: Quick command to remove a user from the mute list. Full management of mute lists is available in the `/settings` menu.
*   `/mute_all`: Enable "Mute All" mode (receive notifications only from users on the allow list). Full management of mute lists is available in the `/settings` menu.
*   `/unmute_all`: Disable "Mute All" mode (receive notifications for everyone not on the block list). The allow list will be cleared. Full management of mute lists is available in the `/settings` menu.
*   `/toggle_noon`: Quick toggle for the "Not on Online" feature. This feature is also configurable in the `/settings` menu.
*   `/my_noon_status`: Check your "Not on Online" feature status.
*   `/kick` (Telegram administrators only): Kick a TeamTalk user (selection via buttons).
*   `/ban` (Telegram administrators only): Ban a TeamTalk user (selection via buttons).

### TeamTalk Commands (in private messages to the bot)

*   `/sub`: Get a link to subscribe to Telegram notifications. This process will also link your TeamTalk account for the "Not on Online" (NOON) feature, which will be initially disabled. If you are already subscribed and NOON-linked to this TeamTalk account, your existing NOON enabled/disabled status will be preserved.
*   `/unsub`: Get a link to unsubscribe from notifications. This will remove your subscription and all associated data and feature configurations (including any "Not on Online" settings) from the bot.
*   `/add_admin <Telegram_ID_1> <Telegram_ID_2> ...`: (Only for `ADMIN_USERNAME` from `.env`) Add Telegram bot administrators.
*   `/remove_admin <Telegram_ID_1> <Telegram_ID_2> ...`: (Only for `ADMIN_USERNAME` from `.env`) Remove Telegram bot administrators.
*   `/not on online`: Set up or re-confirm the "Not on Online" (NOON) feature. This method will enable NOON by default upon successful linking via Telegram.
*   `/help`: Show help for TeamTalk commands.

Any other text message sent to the bot in a TeamTalk PM will be forwarded to `TG_ADMIN_CHAT_ID` if specified.

## "Not on Online" (NOON) Feature Setup

The "Not on Online" (NOON) feature allows Telegram notifications from this bot to be delivered silently if your linked TeamTalk user is currently online. This helps reduce noise if you are actively using TeamTalk.

You can set up the link between your Telegram account and your TeamTalk username in two ways:

**Method 1: Using the `/sub` command (Recommended for new users)**
1.  Send the `/sub` command to the bot in a private message in TeamTalk.
2.  The bot will reply in TeamTalk with a Telegram deeplink.
3.  Open this link. It will lead to your Telegram bot.
4.  Press "Start" in Telegram. The bot will confirm your subscription and that the NOON feature has been linked with your TeamTalk account.
5.  By default, for this method, the NOON feature will be **disabled**. You can enable it using the `/toggle_noon` command in Telegram or the corresponding option in the `/settings` menu.
6.  If you were already subscribed and NOON-linked to this same TeamTalk account, clicking the `/sub` link again will not change your existing NOON enabled/disabled status.

**Method 2: Using the `/not on online` command**
1.  Send the `/not on online` command to the bot in a private message in TeamTalk.
2.  The bot will reply in TeamTalk with a Telegram deeplink.
3.  Open this link. It should lead to your Telegram bot.
4.  Press "Start" in Telegram. The bot will confirm the setup.
5.  By default, for this method, the NOON feature will be **enabled**.

Once set up and enabled, if your linked TeamTalk account is online on the server, notifications from the bot to Telegram will be delivered silently. You can use the `/toggle_noon` command in Telegram or the option in the `/settings` menu to enable or disable the silent notification behavior, and `/my_noon_status` to check its current state.

## Contributing

Suggestions for improvements and bug reports are welcome! Please create Issues or Pull Requests in the repository.

## License

This project is licensed under the **GNU General Public License v3.0**.
The full text of the license can be found in the `LICENSE` file in the root of the repository or at [https://www.gnu.org/licenses/gpl-3.0.html](https://www.gnu.org/licenses/gpl-3.0.html).