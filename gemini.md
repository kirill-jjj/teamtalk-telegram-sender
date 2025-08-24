This document is the single source of truth for any agent contributing to this codebase. Its purpose is to ensure consistency, quality, and maintainability. Adherence to these principles is mandatory for all contributions.

## Golden Rules for the AI Assistant

*   **Analyze First:** Before writing any code, always use tools to understand existing patterns. Use **`rg` (ripgrep)** for fast, repository-aware code searching, `glob` for file structure analysis, and `read_file` to examine specific files. This is preferable to using the more generic `search_file_content` tool.
*   **Services Hold Business Logic:** All business logic **must** reside in the `bot/services` layer. This includes orchestrating data from repositories and performing actions.
*   **Handlers are Thin:** Handlers in `bot/telegram_bot/handlers` and `bot/teamtalk_bot/command_handlers` must be "thin." Their only job is to parse incoming requests, call a single service method, and present the result. They should **never** contain business logic.
*   **Use `replace` for Modifications:** For changing existing code, the `replace` tool is strongly preferred over `write_file` due to its precision and safety. `write_file` should only be used for creating new files or for large-scale refactoring of an entire file.
*   **Follow Existing Patterns:** Mimic the style, structure, and conventions of the surrounding code. This is more important than any personal preference.
*   **Validate Your Work:** After making changes, always run the project's validation suite: `uv run ruff format`, `uv run ruff check --fix`, `uv run mypy`, and `uv run pytest`.

---

## Table of Contents
1.  [Project Overview](#1-project-overview)
2.  [Core Architectural Principles](#2-core-architectural-principles)
    1.  [Dependency Injection (DI)](#21-dependency-injection-di)
    2.  [Event-Driven Architecture](#22-event-driven-architecture)
    3.  [Separation of Concerns (SoC)](#23-separation-of-concerns-soc)
3.  [Database and Migrations](#3-database-and-migrations)
4.  [Internationalization (i18n)](#4-internationalization-i18n)
5.  [Code Quality and Contribution Guidelines](#5-code-quality-and-contribution-guidelines)
6.  [Development Workflow](#6-development-workflow)
7.  [Codebase Map (Where to Find What)](#7-codebase-map-where-to-find-what)
8.  [Adding a New Dependency (Service)](#8-adding-a-new-dependency-service)
9.  [Debugging](#9-debugging)
10. [Using Local Documentation](#10-using-local-documentation)

---

## Development Environment
**Operating System:** This project is developed on **Windows**. Do not use Linux-specific shell commands (e.g., `rm`, `ls`, `grep`). Use Windows equivalents (`del`, `dir`, `findstr`) or cross-platform tools when available.

---

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
*   Dishka (Dependency Injection)
*   py-talk-ex
*   SQLModel (ORM) & Alembic (Migrations)
*   Pydantic (Configuration)

## 2. Core Architectural Principles

The architecture is designed to be modular, testable, and maintainable. Any changes or new features must align with these principles.

### 2.1. Dependency Injection (DI)
This is the central architectural pattern of the application. Dependencies are managed by the `dishka` library and defined in `bot/di_providers.py`.

*   **No Global State:** Do not instantiate global clients (like `Bot` or `Dispatcher`) or session factories outside the main application setup.
*   **Use `dishka` Providers:** Handlers and services receive necessary dependencies (like database sessions, repositories, other services, or caches) via `dishka`'s injection mechanism.
*   **Explicit is Better than Implicit:** Functions should receive their dependencies as explicit arguments, type-hinted with `FromDishka[...]`.

### 2.2. Event-Driven Architecture
To ensure loose coupling between the major components of the application (`telegram_bot` and `teamtalk_bot`), the system uses an event-driven pattern facilitated by an `EventBus`.

*   **Publisher (`PytalkEventRouter`):** This is the primary publisher. It listens for raw events from the `pytalk` library and translates them into meaningful domain events for the rest of the application. It knows nothing about who is listening.
*   **Events:** Events are simple Pydantic models defined in `bot/teamtalk_bot/events.py` that represent a specific business action (e.g., `UserJoinedEvent`, `ReplyToTeamTalkUserEvent`).
*   **Subscribers (Handlers):** Components that need to react to events subscribe to specific event types on the `EventBus`. These handlers are typically located in `bot/event_handlers/` and contain the logic to perform actions based on the event data (e.g., sending a Telegram notification).

This pattern ensures that the `teamtalk_bot` can operate and be tested independently of the `telegram_bot`, and vice-versa.

### 2.3. Separation of Concerns (SoC)
The codebase is organized into distinct layers and modules, each with a single, well-defined responsibility. Adhering to this separation is critical for maintainability.

#### Target Architecture
*   **Handlers (`bot/telegram_bot/handlers`, `bot/teamtalk_bot/command_handlers`)**
    *   **Role:** Entry point for user interaction.
    *   **Responsibilities:**
        *   Parse incoming messages, commands, or callback queries.
        *   Extract necessary data (e.g., user ID, arguments).
        *   Call **one** appropriate method from a **Service** layer class.
        *   Present the result from the service to the user (e.g., sending a message, editing a keyboard).
    *   **Rule:** Handlers **must be thin**. They should **never** contain business logic, database queries, or complex state manipulation.

*   **Services (`bot/services`)**
    *   **Role:** The core of the application's business logic.
    *   **Responsibilities:**
        *   Contain all business rules and use case logic (e.g., how to subscribe a user, what steps to take to ban someone).
        *   Orchestrate operations between different components, primarily repositories.
        *   Interact with the database **only** through the `Unit of Work (UoW)` and its repositories.
        *   May call other services to compose more complex operations.
    *   **Rule:** If it's a business rule or a multi-step process, it belongs in a service.

*   **Repositories (`bot/database/repositories`)**
    *   **Role:** Data Access Layer (DAL).
    *   **Responsibilities:**
        *   Provide a clean API for accessing database tables (e.g., `get_by_id`, `get_all`, custom queries).
        *   Abstract away the specifics of `SQLModel` or `SQLAlchemy` queries.
    *   **Rule:** Repositories should **only** contain database query logic. They do not contain business rules and are always accessed via the `UoW` in the service layer.

#### Working with Existing Code
You may encounter business logic within handlers. This is a known area for future refactoring. When modifying an existing handler that contains business logic, you have two options:

*   **Option A (Preferred):** If the task is small, refactor the existing logic out of the handler and into a new or existing service, then add your new logic in the service. Propose this refactoring to the user as part of your plan.
*   **Option B:** If the change is very minor (e.g., fixing a typo in a string), you can make the change directly in the handler. However, for any logic changes, prefer Option A.

The goal is to leave the code better than you found it. Always strive to move business logic to the service layer when you touch a related part of the code.

## 3. Database and Migrations
*   **Models:** All database tables are defined as `SQLModel` classes in `bot/models.py`.
*   **Migrations:** Database schema changes are managed by `Alembic`. Any modification to `bot/models.py` requires a new migration.
*   **Migrations Must Be Non-Destructive:** **The paramount principle of database migration is that existing user data must NEVER be lost.** `autogenerate` is a tool, not a source of truth. It can misinterpret changes like column renames as "drop and add," leading to catastrophic data loss. All generated scripts require careful manual inspection and, if necessary, correction.

## 4. Internationalization (i18n)
*   All user-facing strings **must** be wrapped in a `_()` call for translation.
*   The workflow is managed by `Babel` via `uv run i18n [update|compile]`.

## 5. Code Quality and Contribution Guidelines

These rules are enforced by the `ruff` configuration in `pyproject.toml` and must be followed.

### 5.1. Core Principles
*   **Embrace Modern Python:** This project targets Python 3.11+. All new code should leverage modern syntax and features (e.g., `|` for union types, structural pattern matching where appropriate) from the outset. Do not write legacy code with the expectation that tooling will fix it.
*   **Single Responsibility Principle (SRP):** A function or class should do one thing and do it well. Handlers should delegate complex logic to service functions.
*   **Don't Repeat Yourself (DRY):** If you write the same code block more than once, refactor it into a reusable utility function. Before creating a new utility function, check existing modules for a suitable location.
*   **Simplicity and The Zen of Python:** Prefer simple, clear, and explicit code over complex, clever, and implicit solutions.

### 5.2. Integrating External Code
Before integrating any code from external sources (e.g., web snippets, other AI outputs), it **must** be rigorously sanitized. This process involves:
1.  Stripping all non-essential comments, especially AI-generated artifacts (`# changed here`, `# from my knowledge`).
2.  Formatting and linting the code against the project's `ruff` configuration (`uv run ruff format .` and `uv run ruff check --fix .`).
3.  Thoroughly reviewing the code for logic, security, and adherence to project architecture before integration.

### 5.3. Commenting
*   **English-Only:** All comments, docstrings, and variable names must be written in English to ensure universal understanding.
*   **No Historical Comments:** Do not add comments like `# added`, `# changed`, or `# refactored`. Git history serves this purpose.
*   **No Obvious Comments:** Do not explain *what* the code is doing (e.g., `# increment counter`). The code should be clear enough to explain itself.
*   **Use Comments to Explain *Why*:** Comments should only be used to explain complex logic, trade-offs, or the reasoning behind a non-obvious implementation choice.

### 5.4. Code Maintenance
*   **Dead Code Must Be Removed:** Do not comment out unused imports, functions, or blocks of code. Delete them. Version control is your safety net.

### 5.5. Naming Conventions

Clear and predictable naming is critical for code readability and maintainability. Names must reflect the **essence** of a component (what it does), not its technical implementation (how it does it) or its trigger mechanism. All names must be concise and free of redundancy.

#### 5.5.1. Avoid Redundant Prefixes and Suffixes

Prefixes and suffixes that state the obvious, such as `handle_`, `process_`, `cq_`, or `_action`, should be avoided. The context of a component is typically clear from its location, decorators, or usage. Adding these terms often creates unnecessary clutter.

*   **Avoid:**
    *   `handle_tt_subscribe_command` — The `handle_` prefix is redundant for a command handler.
    *   `process_deeplink` — The verb "process" is ambiguous. Prefer a more descriptive verb that clarifies the action, such as `resolve_deeplink` or `execute_deeplink`.
    *   `cq_show_language_menu` — The `cq_` (callback_query) prefix is unnecessary when a decorator like `@router.callback_query` already defines the context.
    *   `SubscriberActionCallback` — The `Action` suffix is redundant. A callback inherently represents an action.

*   **Prefer:**
    *   `on_subscribe_command` or `subscribe_command`.
    *   `resolve_deeplink` or `execute_deeplink`.
    *   `show_language_menu`.
    *   `SubscriberCallback`.

#### 5.5.2. Eliminate Superfluous Words

Words like `specific`, `full`, `generic`, `data`, and `info` are often implied and can be omitted. A function or class name should be as concise as possible without losing its meaning.

*   **Avoid:**
    *   `delete_full_user_profile` — A deletion function is expected to be complete. The word `full` is superfluous.
    *   `ToggleMuteSpecificCallback` — A callback's context typically implies that it acts on a specific entity.
    *   `_create_generic_paginated_list_keyboard` — A function's generic nature should be conveyed by its parameters and implementation, not by the word "generic" in its name.
    *   `WorkflowData`, `SubscriberInfo` — Names ending in `Data` or `Info` can often be made more descriptive.

*   **Prefer:**
    *   `delete_user_profile`.
    *   `ToggleMuteCallback`.
    *   `create_paginated_keyboard`.
    *   `WorkflowContext`, `SubscriberView` (or simply `Subscriber` if it represents a data model).

#### 5.5.3. Focus on Purpose, Not Implementation

A function's name should communicate its primary purpose, not summarize its implementation steps.

*   **Avoid:**
    *   `_generate_and_reply_deeplink` — This describes the implementation, not the singular goal.
    *   `_is_username_effectively_muted` — The word "effectively" hints at the implementation detail (e.g., checking multiple conditions). The function's core purpose is to check the mute status.
    *   `_orchestrate_user_banning` — Terms like "orchestrate" or "manage" are often too abstract and can be replaced with a more direct verb.

*   **Prefer:**
    *   `reply_with_deeplink`.
    *   `is_muted`.
    *   `apply_ban` or `ban_user`.

#### 5.5.4. Use Verbs for Actions and Nouns for Data

Adherence to this fundamental principle is essential for clarity.

*   **Functions and methods** must begin with a verb that describes the action they perform (e.g., `get_user`, `create_keyboard`, `send_message`).
*   **Classes, variables, and data structures** must be nouns that describe the entity they represent (e.g., `User`, `Settings`, `main_menu_keyboard`).
*   **Boolean variables or functions** should be named to read like a question (e.g., `is_admin`, `is_ready`, `has_permissions`).

### 5.6. Code Modification
When modifying existing code, the `replace` tool is strongly preferred over `write_file`.

*   **Precision:** The `replace` tool is designed for surgical precision. It requires a significant amount of context (the `old_string` parameter) around the code to be changed, which ensures that the modification is applied exactly where intended. This minimizes the risk of accidental changes or corrupting the file.
*   **Safety:** Unlike `write_file`, which overwrites the entire file, `replace` only targets a specific block of text. This makes it a much safer option for small to medium-sized changes.
*   **Usage:** To use `replace` effectively, first use `read_file` to get the exact content of the file. Always re-read the file immediately before using `replace` to ensure the `old_string` accurately reflects the current file content. Then, construct the `old_string` parameter by copying at least 3-5 lines of code before and after the target block, including all original whitespace and indentation. The `new_string` parameter will contain the replacement code.

**Example Workflow:**
1.  `read_file('path/to/file.py')`
2.  Identify the block to change from the output.
3.  Use `replace` with the `old_string` containing the identified block plus its surrounding context, and the `new_string` containing the updated code.

Using `write_file` for minor changes is discouraged and should only be used when creating a new file or performing a very large-scale refactoring that makes `replace` impractical.

### 5.7. Linting and Formatting
All code must be validated against `ruff` before committing. The key commands are `uv run ruff check --fix .` and `uv run ruff format .`. Key enforced rules include:
*   **`D` (pydocstyle):** All public modules, functions, classes, and methods **must** have a docstring in the Google convention. This is non-negotiable.
*   **`SIM` (flake8-simplify):** Code must be simplified where possible. `ruff --fix` will handle most of this.
*   **`T20` (flake8-print):** The use of `print()` is **forbidden** in the application codebase. Use the `logging` module instead. `print()` is only permissible in the `scripts/` directory and the main `sender.py` entrypoint.
*   **`A` (flake8-builtins):** Do not shadow built-in names like `list`, `dict`, or `id`.
*   **`UP` (pyupgrade):** Code must conform to modern Python 3.11+ syntax.

## 6. Development Workflow

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
    3.  Run `uv run mypy` to validate type hints.
    4.  Run `uv run pytest` to execute the test suite.
    5.  **Runtime Verification:** After all static checks pass, you **must** attempt to run the application with `uv run sender` to ensure it initializes without errors. **Do not proceed to the commit step if the application fails to start.**

5.  **Commit:** After successfully implementing and validating a task (including the runtime verification), you **must** always proactively offer to create a commit for the changes.

    *   **Tooling & Process:**
        1.  **Compose the Message:** For any non-trivial change, compose the full, multi-line commit message in a temporary file named `commit_message.txt` using the `write_file` tool. Always use an absolute path for `commit_message.txt` to avoid issues. This is the **required workflow** because the `-m` flag is not suitable for the detailed, multi-line messages expected in this project.
        2.  **Commit from File:** Run the commit command using the file: `git commit -F commit_message.txt`. This ensures the message is formatted correctly.
        3.  **Clean Up:** Delete the temporary file after the commit is successful.

    *   **Format:** The commit message must follow this structure:
        ```
        <emoji> <type>(<scope>): <subject>
        <BLANK LINE>
        <body>
        <BLANK LINE>
        <footer>
        ```

    *   **Components:**
        *   **Emoji:** Start with a relevant emoji from the Gitmoji standard.
        *   **Type:** Must be one of the following:
            *   `feat`: A new feature.
            *   `fix`: A bug fix.
            *   `docs`: Documentation only changes.
            *   `style`: Changes that do not affect the meaning of the code (white-space, formatting, etc).
            *   `refactor`: A code change that neither fixes a bug nor adds a feature.
            *   `perf`: A code change that improves performance.
            *   `test`: Adding missing tests or correcting existing tests.
            *   `build`: Changes that affect the build system or external dependencies.
            *   `ci`: Changes to our CI configuration files and scripts.
            *   `chore`: Other changes that don't modify src or test files.
        *   **Scope (optional):** A noun describing the section of the codebase affected (e.g., `auth`, `db`, `telegram_handlers`).
        *   **Subject:** A concise description of the change in the imperative mood (e.g., "Add `replace` tool guide", not "Added..."). No capitalization, no period at the end.
        *   **Body (optional):** A more detailed explanation of the changes. Explain the *why* behind the change, not the *how*.
        *   **Footer (optional):** Contains "BREAKING CHANGE:" for breaking changes or references to issues (e.g., "Closes #123").

    *   **Gitmoji Quick Reference:**
        | Emoji | Code | Type | Description |
        |---|---|---|---|
        | ✨ | `:sparkles:` | `feat` | Introduce a new feature. |
        | 🐛 | `:bug:` | `fix` | Fix a bug. |
        | 📚 | `:books:` | `docs` | Write or update documentation. |
        | ♻️ | `:recycle:` | `refactor` | Refactor code. |
        | ✅ | `:white_check_mark:` | `test` | Add, update, or pass tests. |
        | 🔧 | `:wrench:` | `chore` | Add or update configuration files. |
        | 🚀 | `:rocket:` | `chore` | Deploy stuff. |
        | 💄 | `:lipstick:` | `style` | Add or update the UI and style files. |
        | 🔥 | `:fire:` | `refactor` | Remove code or files. |
        | 💥 | `:boom:` | `feat` | Introduce breaking changes. |
        | 📦 | `:package:` | `build` | Add or update compiled files or packages. |
        | 👷 | `:construction_worker:` | `ci` | Add or update CI build system. |

## 7. Codebase Map (Where to Find What)

Use this as a quick guide to locate code for common tasks:

*   **User-facing text & keyboards:** Look in `bot/telegram_bot/handlers/` for the command logic and `bot/telegram_bot/keyboards/` for the button layouts and text. User-facing strings must be wrapped in `_()` for localization.
*   **Business Logic (e.g., subscribing a user, banning):** All core logic should be in the `bot/services/` directory. Start your search here for how the application *works*.
*   **Database Schema:** The single source of truth for the database structure is `bot/models.py`.
*   **Database Queries:** All `SELECT`, `INSERT`, `UPDATE`, `DELETE` operations are encapsulated within repositories in `bot/database/repositories/`.
*   **Dependency Injection:** To see how components are wired together or to add a new one, see `bot/di_providers.py`.
*   **TeamTalk Events (Join/Leave):** The initial handling and routing of raw events from the `py-talk-ex` library happens in `bot/teamtalk_bot/pytalk_event_router.py`.
*   **Startup & Shutdown Logic:** See `bot/lifecycle.py`.

## 8. Adding a New Dependency (Service)

This project uses `dishka` for dependency injection. To add a new service and make it available to a handler, follow these steps:

1.  **Create the Service:** Write your new service class in a file within the `bot/services/` directory.
2.  **Add a Provider:** Open `bot/di_providers.py`. In the appropriate provider class (`AppProvider` for app-level singletons, `RequestProvider` for per-request instances), add a new `@provide` method that creates and returns an instance of your service.
3.  **Inject the Service:** In the `__init__` or handler function where you need the service, add it as a parameter with the type hint `FromDishka[YourNewService]`. Dishka will automatically provide it.

## 9. Debugging

Direct `print()` calls are forbidden in the application code (`bot/`, `sender.py`) and will be caught by the linter.

*   **Recommended Method:** Use the `logging` module. For temporary debugging, you can add `logger.debug("My variable: %s", my_variable)`. Remember to remove these debug statements before creating a commit.
*   **Running with Debug Logs:** To see debug-level logs, you may need to adjust the logging level in `bot/logging_setup.py` locally. Do not commit changes to this file.

## 10. Using Local Documentation

The `ai-docs` directory contains offline documentation for the key libraries used in this project. Before performing a complex task involving Aiogram, Dishka, or another major library, you should consult this documentation.

**Workflow:**
1.  The contents of `ai-docs` are ignored by default. You must explicitly bypass this rule to see the files.
2.  Use `glob` to find relevant documentation files. You must set `respect_git_ignore` to `False`. For example: `glob(pattern='ai-docs/aiogram-docs/**/*.rst', respect_git_ignore=False)`.
3.  Once you have a list of files, use `read_many_files` or `read_file` to get their content.
4.  Use the information to ensure your code modifications are idiomatic and use the library's API correctly.