"""unify_master_to_refactor_schema

Revision ID: 1a2b3c4d5e6f
Revises:
Create Date: 2025-07-05 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table  # Keep for potential use in data migrations if needed

# revision identifiers, used by Alembic.
revision: str = "8677509804ef"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Helper function to check if a table exists
def _table_exists(table_name, conn):
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


# Helper function to check if a column exists in a table
def _column_exists(table_name, column_name, conn):
    if not _table_exists(table_name, conn):
        return False
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """
    This function updates the database schema from the 'master' branch state
    to the 'refactor' branch state, OR initializes a new database to the
    'refactor' branch state.
    """
    conn = op.get_bind()
    print("Starting database schema setup/upgrade...")

    # --- Section 1: Ensure all current tables exist with correct schema ---
    print("Step 1/N: Ensuring core table structures...")

    # UserSettings Table
    if not _table_exists("user_settings", conn):
        print("  - Creating 'user_settings' table...")
        op.create_table(
            "user_settings",
            sa.Column("telegram_id", sa.Integer(), nullable=False),
            sa.Column("language_code", sa.String(), nullable=False),
            # Adjusted for common enum default
            sa.Column("notification_settings", sa.String(), nullable=False, server_default="all"),
            # Adjusted
            sa.Column("mute_list_mode", sa.String(), nullable=False, server_default="blacklist"),
            sa.Column("teamtalk_username", sa.String(), nullable=True),
            sa.Column("not_on_online_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("not_on_online_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.PrimaryKeyConstraint("telegram_id"),
        )
        # unique=False for PK index is fine
        op.create_index(op.f("ix_user_settings_telegram_id"), "user_settings", ["telegram_id"], unique=False)
        # Should be unique if it's a lookup key
        op.create_index(
            op.f("ix_user_settings_teamtalk_username"), "user_settings", ["teamtalk_username"], unique=False
        )
        print("  - Table 'user_settings' created.")
    else:
        print("  - Table 'user_settings' already exists.")

    # MutedUser Table (FK depends on user_settings)
    if not _table_exists("muted_users", conn):
        print("  - Creating 'muted_users' table...")
        op.create_table(
            "muted_users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("muted_teamtalk_username", sa.String(), nullable=False),
            sa.Column("user_settings_telegram_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_settings_telegram_id"],
                ["user_settings.telegram_id"],
                name=op.f("fk_muted_users_user_settings_telegram_id_user_settings"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_muted_users_muted_teamtalk_username"), "muted_users", ["muted_teamtalk_username"], unique=False
        )
        print("  - Table 'muted_users' created.")
    else:
        print("  - Table 'muted_users' already exists.")

    # SubscribedUser Table
    if not _table_exists("subscribed_users", conn):
        print("  - Creating 'subscribed_users' table...")
        op.create_table(
            "subscribed_users",
            sa.Column("telegram_id", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("telegram_id"),
        )
        op.create_index(op.f("ix_subscribed_users_telegram_id"), "subscribed_users", ["telegram_id"], unique=False)
        print("  - Table 'subscribed_users' created.")
    else:
        print("  - Table 'subscribed_users' already exists.")

    # Admin Table
    if not _table_exists("admins", conn):
        print("  - Creating 'admins' table...")
        op.create_table(
            "admins", sa.Column("telegram_id", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("telegram_id")
        )
        op.create_index(op.f("ix_admins_telegram_id"), "admins", ["telegram_id"], unique=False)
        print("  - Table 'admins' created.")
    else:
        print("  - Table 'admins' already exists.")

    # Deeplink Table
    if not _table_exists("deeplinks", conn):
        print("  - Creating 'deeplinks' table...")
        op.create_table(
            "deeplinks",
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),  # Assuming DeeplinkAction enum is string
            sa.Column("payload", sa.String(), nullable=True),
            sa.Column("expected_telegram_id", sa.Integer(), nullable=True),
            sa.Column("expiry_time", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("token"),
        )
        op.create_index(op.f("ix_deeplinks_token"), "deeplinks", ["token"], unique=False)
        print("  - Table 'deeplinks' created.")
    else:
        print("  - Table 'deeplinks' already exists.")

    # BanList Table
    if not _table_exists("ban_list", conn):
        print("  - Creating 'ban_list' table...")
        op.create_table(
            "ban_list",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("telegram_id", sa.Integer(), nullable=True),
            sa.Column("teamtalk_username", sa.String(), nullable=True),
            sa.Column("ban_reason", sa.String(), nullable=True),
            sa.Column("banned_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ban_list_telegram_id"), "ban_list", ["telegram_id"], unique=False)
        op.create_index(op.f("ix_ban_list_teamtalk_username"), "ban_list", ["teamtalk_username"], unique=False)
        print("  - Table 'ban_list' created.")
    else:
        print("  - Table 'ban_list' already exists.")

    # --- Section 2: Conditional Data Migrations from old 'master' schema ---
    print("Step 2/N: Attempting data migrations if old schema elements exist...")

    # Migration for: `muted_users` string to `MutedUser` table
    if _table_exists("user_settings", conn) and _column_exists("user_settings", "muted_users", conn):
        print("  - Old 'user_settings.muted_users' column found. Migrating data...")
        # This assumes muted_users table was created in Section 1 if it didn't exist.
        # If muted_users table was pre-existing from an even older state, this logic might need adjustment.
        # For this specific migration, we assume if user_settings.muted_users exists, we are coming from 'master'.

        # Re-fetch table metadata for bulk_insert if muted_users was just created
        muted_users_table_ref = sa.Table(
            "muted_users",
            sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("muted_teamtalk_username", sa.String),
            sa.Column("user_settings_telegram_id", sa.Integer),
        )

        old_user_settings_data = conn.execute(sa.text("SELECT telegram_id, muted_users FROM user_settings")).fetchall()
        users_to_insert = []
        for telegram_id, muted_users_str in old_user_settings_data:
            if muted_users_str and muted_users_str.strip():
                usernames = [name.strip() for name in muted_users_str.split(",") if name.strip()]
                for username in usernames:
                    # Check if this muted user already exists for this telegram_id
                    # to prevent duplicates if script is re-runnable.
                    # This check is simplified; a more robust check would query muted_users table.
                    # For now, assume we insert if the old column existed.
                    users_to_insert.append(
                        {"muted_teamtalk_username": username, "user_settings_telegram_id": telegram_id}
                    )

        if users_to_insert:
            # Before bulk insert, ensure no constraints are violated if this is run multiple times.
            # This might require deleting existing entries if this script part is re-run
            # on an already partially migrated DB.
            # For simplicity, we assume this part of script runs once cleanly.
            op.bulk_insert(muted_users_table_ref, users_to_insert)
            print(f"    - Migrated {len(users_to_insert)} muted user entries to 'muted_users' table.")

        with op.batch_alter_table("user_settings", schema=None) as batch_op:
            batch_op.drop_column("muted_users")
        print("  - Dropped old 'muted_users' column from 'user_settings'.")
    else:
        print(
            "  - Old 'user_settings.muted_users' column not found or 'user_settings' table missing. "
            "Skipping data migration for muted_users string."
        )

    # Migration for: `mute_all` (bool) to `mute_list_mode` (string)
    if _table_exists("user_settings", conn):
        if _column_exists("user_settings", "mute_all", conn):
            print("  - Old 'user_settings.mute_all' column found. Migrating to 'mute_list_mode'...")
            if not _column_exists("user_settings", "mute_list_mode", conn):
                with op.batch_alter_table("user_settings", schema=None) as batch_op:
                    batch_op.add_column(
                        sa.Column("mute_list_mode", sa.String(), nullable=False, server_default="blacklist")
                    )
                print("    - Added 'mute_list_mode' column.")

            # Use temporary table objects for data migration
            user_settings_table_for_mute_all = sa.Table(
                "user_settings",
                sa.MetaData(),
                sa.Column("telegram_id", sa.Integer, primary_key=True),  # Assuming telegram_id is PK
                sa.Column("mute_all", sa.Boolean),
                sa.Column("mute_list_mode", sa.String),
            )
            op.execute(
                user_settings_table_for_mute_all.update()
                .where(user_settings_table_for_mute_all.c.mute_all)
                .values(mute_list_mode="whitelist")
            )
            op.execute(
                user_settings_table_for_mute_all.update()
                .where(sa.not_(user_settings_table_for_mute_all.c.mute_all))
                .values(mute_list_mode="blacklist")
            )
            print("    - Migrated data from 'mute_all' to 'mute_list_mode'.")

            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.drop_column("mute_all")
            print("  - Dropped old 'mute_all' column.")
        elif not _column_exists("user_settings", "mute_list_mode", conn):
            # mute_all doesn't exist, but mute_list_mode also doesn't (should have been created in Section 1)
            # This case implies user_settings table was old and didn't get mute_list_mode from Section 1.
            print("  - 'user_settings.mute_all' not found, ensuring 'mute_list_mode' exists...")
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("mute_list_mode", sa.String(), nullable=False, server_default="blacklist")
                )
            print("    - Added 'mute_list_mode' column with default.")
        else:
            print(
                "  - 'user_settings.mute_list_mode' already exists or 'mute_all' not found. "
                "Skipping mute_all migration."
            )

    # Migration for: `language` column to `language_code`
    if _table_exists("user_settings", conn):
        if _column_exists("user_settings", "language", conn) and not _column_exists(
            "user_settings", "language_code", conn
        ):
            print("  - Old 'user_settings.language' column found. Renaming to 'language_code'...")
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.alter_column("language", new_column_name="language_code", existing_type=sa.String())
            print("  - Column renamed.")
        elif not _column_exists("user_settings", "language_code", conn):
            # language doesn't exist, but language_code also doesn't (should have been created in Section 1)
            print("  - 'user_settings.language' not found, ensuring 'language_code' exists...")
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("language_code", sa.String(), nullable=False, server_default="en")  # Provide a default
                )
            print("    - Added 'language_code' column with default.")
        else:
            print("  - 'user_settings.language_code' already exists or 'language' not found. Skipping language rename.")

    print("Step 3/N: Finalizing schema setup.")
    print("✅ Database schema setup/upgrade complete.")


def downgrade() -> None:
    """
    This function rolls back the changes, returning the schema to the 'master' branch state.
    Useful for testing or in case of problems.
    """
    print("Starting downgrade from 'refactor' schema to 'master' schema...")

    # --- Rollback 4: Drop `BanList` table ---
    print("Step 1/4: Dropping 'ban_list' table...")
    op.drop_index(op.f("ix_ban_list_teamtalk_username"), table_name="ban_list")
    op.drop_index(op.f("ix_ban_list_telegram_id"), table_name="ban_list")
    op.drop_table("ban_list")
    print("  - Table 'ban_list' dropped.")

    # --- Rollback 3: Rename `language_code` back to `language` ---
    print("Step 2/4: Renaming 'language_code' back to 'language'...")
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.alter_column("language_code", new_column_name="language", existing_type=sa.String())
    print("  - Column renamed.")

    # --- Rollback 2: Revert `mute_list_mode` to `mute_all` ---
    print("Step 3/4: Reverting 'mute_list_mode' to 'mute_all'...")
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mute_all", sa.BOOLEAN(), nullable=False, server_default=sa.false()))
    print("  - Added back 'mute_all' column.")

    user_settings_table_ref = table(
        "user_settings", column("mute_all", sa.Boolean), column("mute_list_mode", sa.String)
    )
    op.execute(
        user_settings_table_ref.update()
        .where(user_settings_table_ref.c.mute_list_mode == "whitelist")
        .values(mute_all=True)
    )
    op.execute(
        user_settings_table_ref.update()
        .where(user_settings_table_ref.c.mute_list_mode == "blacklist")
        .values(mute_all=False)
    )
    print("  - Migrated data from 'mute_list_mode' back to 'mute_all'.")

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("mute_list_mode")
    print("  - Dropped 'mute_list_mode' column.")

    # --- Rollback 1: Revert MutedUser table to 'muted_users' string ---
    print("Step 4/4: Reverting MutedUser table to 'muted_users' string...")
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("muted_users", sa.VARCHAR(), nullable=False, server_default=""))
    print("  - Added back 'muted_users' column.")

    conn = op.get_bind()
    # GROUP_CONCAT is an SQLite-specific function that is well-suited for this task.
    query = sa.text("""
        UPDATE user_settings
        SET muted_users = (
            SELECT GROUP_CONCAT(muted_teamtalk_username, ',')
            FROM muted_users
            WHERE muted_users.user_settings_telegram_id = user_settings.telegram_id
        )
        WHERE EXISTS (
            SELECT 1 FROM muted_users WHERE muted_users.user_settings_telegram_id = user_settings.telegram_id
        );
    """)
    conn.execute(query)
    print("  - Migrated data from 'muted_users' table back to string column.")

    op.drop_index(op.f("ix_muted_users_muted_teamtalk_username"), table_name="muted_users")
    op.drop_table("muted_users")
    print("  - Dropped 'muted_users' table.")

    print("✅ Downgrade to 'master' schema complete.")
