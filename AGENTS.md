This document is the single source of truth for any agent contributing to this codebase. Its purpose is to ensure consistency, quality, and maintainability. Adherence to these principles is mandatory for all contributions.

## 1. Project Overview

**Objective:** This project is an asynchronous bot that bridges a **TeamTalk 5** server with **Telegram**.

**Core Functionality:**
*   Relaying user join/leave events from TeamTalk to Telegram.
*   Forwarding private messages from TeamTalk to a Telegram administrator.
*   Providing a comprehensive, interactive settings menu in Telegram.
*   Enabling user administration (kick/ban) from within Telegram.
*   Supporting internationalization (i18n) via `gettext`.

**Primary Technologies:**
*   Python 3.11+
*   Aiogram 3
*   py-talk-ex
*   SQLModel (ORM) & Alembic (Migrations)
*   Pydantic (Configuration)

## 2. Core Architectural Principles

The architecture is designed to be modular, testable, and maintainable. Any changes or new features must align with these principles.

### 2.1. Dependency Injection (DI)
This is the central architectural pattern of the application. Shared state, services, and resources are managed through a central `Services` container.

*   **No Global State:** Do not instantiate global clients (like `Bot` or `Dispatcher`) or session factories outside the main application setup.
*   **Use the `Services` Container:** Handlers and other components receive necessary dependencies (like database sessions, bot instances, or caches) from the `workflow_data` of the `aiogram` Dispatcher, which is populated with the `Services` instance and its components at startup.
*   **Explicit is Better than Implicit:** Functions should receive their dependencies as explicit arguments.

### 2.2. Separation of Concerns (SoC)
The codebase is organized into distinct layers and modules, each with a single responsibility.
*   `bot/core`: Cross-cutting concerns, core enums, and business logic not tied to a specific platform.
*   `bot/database`: Database models (`models.py`), access logic (`crud.py`), and engine/session setup (`engine.py`).
*   `bot/telegram_bot`: All components specific to the Telegram bot, including `handlers`, `keyboards`, and `middlewares`.
*   `bot/teamtalk_bot`: All components specific to the TeamTalk client.
*   `scripts`: Standalone utility scripts for development and maintenance.

## 3. Key Components and State Management

### 3.1. The `Services` Container
Located at `bot/services_container.py`, the `Services` class is the single source of truth for shared application components. It holds:
*   `services.config`: The typed application configuration, loaded from `config.toml`.
*   `services.session_factory`: The SQLAlchemy session factory for database access.
*   `services.bot_event` & `services.bot_message`: `aiogram.Bot` instances.
*   `services.tt_bot`: The `pytalk.TeamTalkBot` instance.
*   `services.connections`: A dictionary of active `TeamTalkConnection` objects.
*   **Caches:** In-memory caches for performance, including `user_settings_cache`, `admin_ids_cache`, and `subscribed_users_cache`.
*   `services.get_translator()`: A method to retrieve a `gettext` translator for a given language.

### 3.2. Database and Migrations
*   **Models:** All database tables are defined as `SQLModel` classes in `bot/models.py`.
*   **Migrations:** Database schema changes are managed by `Alembic`. Any modification to `bot/models.py` requires a new migration.
*   **Migrations Must Be Non-Destructive:** **The paramount principle of database migration is that existing user data must NEVER be lost.** `autogenerate` is a tool, not a source of truth. It can misinterpret changes like column renames as "drop and add," leading to catastrophic data loss. All generated scripts require careful manual inspection and, if necessary, correction.

### 3.3. Internationalization (i18n)
*   All user-facing strings **must** be wrapped in a `_()` call for translation.
*   The workflow is managed by `Babel` via `uv run i18n [update|compile]`.

## 4. Code Quality and Contribution Guidelines

These rules are enforced by the `ruff` configuration in `pyproject.toml` and must be followed.

### 4.1. Core Principles
*   **Embrace Modern Python:** This project targets Python 3.11+. All new code should leverage modern syntax and features (e.g., `|` for union types, structural pattern matching where appropriate) from the outset. Do not write legacy code with the expectation that tooling will fix it.
*   **Single Responsibility Principle (SRP):** A function or class should do one thing and do it well. Handlers should delegate complex logic to service functions.
*   **Don't Repeat Yourself (DRY):** If you write the same code block more than once, refactor it into a reusable utility function. Check `bot/core/utils.py` before creating a new one.
*   **Simplicity and The Zen of Python:** Prefer simple, clear, and explicit code over complex, clever, and implicit solutions.

### 4.2. Integrating External Code
Before integrating any code from external sources (e.g., web snippets, other AI outputs), it **must** be rigorously sanitized. This process involves:
1.  Stripping all non-essential comments, especially AI-generated artifacts (`# changed here`, `# from my knowledge`).
2.  Formatting and linting the code against the project's `ruff` configuration (`uv run ruff format .` and `uv run ruff check --fix .`).
3.  Thoroughly reviewing the code for logic, security, and adherence to project architecture before integration.

### 4.3. Commenting
*   **English-Only:** All comments, docstrings, and variable names must be written in English to ensure universal understanding.
*   **No Historical Comments:** Do not add comments like `# added`, `# changed`, or `# refactored`. Git history serves this purpose.
*   **No Obvious Comments:** Do not explain *what* the code is doing (e.g., `# increment counter`). The code should be clear enough to explain itself.
*   **Use Comments to Explain *Why*:** Comments should only be used to explain complex logic, trade-offs, or the reasoning behind a non-obvious implementation choice.

### 4.4. Code Maintenance
*   **Dead Code Must Be Removed:** Do not comment out unused imports, functions, or blocks of code. Delete them. Version control is your safety net.

### 4.5. Linting and Formatting
All code must be validated against `ruff` before committing. The key commands are `uv run ruff check --fix .` and `uv run ruff format .`. Key enforced rules include:
*   **`D` (pydocstyle):** All public modules, functions, classes, and methods **must** have a docstring in the Google convention. This is non-negotiable.
*   **`SIM` (flake8-simplify):** Code must be simplified where possible. `ruff --fix` will handle most of this.
*   **`T20` (flake8-print):** The use of `print()` is **forbidden** in the application codebase. Use the `logging` module instead. `print()` is only permissible in the `scripts/` directory and the main `sender.py` entrypoint.
*   **`A` (flake8-builtins):** Do not shadow built-in names like `list`, `dict`, or `id`.
*   **`UP` (pyupgrade):** Code must conform to modern Python 3.11+ syntax.

## 5. Development Workflow

Before starting, ensure your environment is set up and all dependencies are installed by running `uv sync --all-extras`.

Follow this workflow for every task.

1.  **Code Implementation:** Write code that adheres to all the principles outlined above.
2.  **Localization (if new user-facing strings were added):**
    1.  Wrap new strings in `_()`.
    2.  Run `uv run i18n update` to update the `.pot` template and the `.po` files.
    3.  Add translations to the `.po` files.
    4.  Run `uv run i18n compile` to create the `.mo` files.
3.  **Database Migration (if `bot/models.py` was changed):**
    1.  Run `uv run migrate revision -m "Descriptive message" --autogenerate`.
    2.  **CRITICAL: Manually inspect the generated migration script for correctness.**
        *   **Data integrity is the highest priority. Under NO circumstances shall a migration lead to data loss for existing users. Never.**
        *   Pay special attention to column renames or type changes. Alembic's `autogenerate` often detects a rename as a `DROP` of the old column and an `ADD` of the new one. This is **unacceptable** as it deletes all data in that column. You **must** manually edit the script to use `op.alter_column()` instead.
        *   Always question if a destructive change (like dropping a table or column) is truly necessary and plan for it carefully.
4.  **Validation:**
    1.  Run `uv run ruff format .` to format the code.
    2.  Run `uv run ruff check --fix .` to check for and fix issues.
    3.  Run `uv run mypy .` to validate type hints.
    4.  Run `uv run pytest` to execute the test suite.
5.  **Commit:** Write a clear and descriptive commit message following the Conventional Commits specification.