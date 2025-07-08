"""unify_master_to_refactor_schema

Revision ID: 1a2b3c4d5e6f
Revises:
Create Date: 2025-07-05 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table  # Removed unused 'text'

# revision identifiers, used by Alembic.
revision: str = "8677509804ef"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Helper function to check if a table exists
def _table_exists(table_name: str, conn: sa.engine.Connection) -> bool:
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


# Helper function to check if a column exists in a table
def _column_exists(table_name: str, column_name: str, conn: sa.engine.Connection) -> bool:
    if not _table_exists(table_name, conn):
        return False
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:  # noqa: PLR0912, PLR0915
    """
    This function updates the database schema from the 'master' branch state
    to the 'refactor' branch state, OR initializes a new database to the
    'refactor' branch state.
    """
    conn = op.get_bind()

    # UserSettings Table
    if not _table_exists("user_settings", conn):
        op.create_table(
            "user_settings",
            sa.Column("telegram_id", sa.Integer(), nullable=False),
            sa.Column("language_code", sa.String(), nullable=False),
            sa.Column("notification_settings", sa.String(), nullable=False, server_default="all"),
            sa.Column("mute_list_mode", sa.String(), nullable=False, server_default="blacklist"),
            sa.Column("teamtalk_username", sa.String(), nullable=True),
            sa.Column("not_on_online_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("not_on_online_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.PrimaryKeyConstraint("telegram_id"),
        )
        op.create_index(op.f("ix_user_settings_telegram_id"), "user_settings", ["telegram_id"], unique=False)
        op.create_index(
            op.f("ix_user_settings_teamtalk_username"), "user_settings", ["teamtalk_username"], unique=False
        )
    else:
        pass

    # MutedUser Table
    if not _table_exists("muted_users", conn):
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
    else:
        pass

    # SubscribedUser Table
    if not _table_exists("subscribed_users", conn):
        op.create_table(
            "subscribed_users",
            sa.Column("telegram_id", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("telegram_id"),
        )
        op.create_index(op.f("ix_subscribed_users_telegram_id"), "subscribed_users", ["telegram_id"], unique=False)
    else:
        pass

    # Admin Table
    if not _table_exists("admins", conn):
        op.create_table(
            "admins", sa.Column("telegram_id", sa.Integer(), nullable=False), sa.PrimaryKeyConstraint("telegram_id")
        )
        op.create_index(op.f("ix_admins_telegram_id"), "admins", ["telegram_id"], unique=False)
    else:
        pass

    # Deeplink Table
    if not _table_exists("deeplinks", conn):
        op.create_table(
            "deeplinks",
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("payload", sa.String(), nullable=True),
            sa.Column("expected_telegram_id", sa.Integer(), nullable=True),
            sa.Column("expiry_time", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("token"),
        )
        op.create_index(op.f("ix_deeplinks_token"), "deeplinks", ["token"], unique=False)
    else:
        pass

    # BanList Table
    if not _table_exists("ban_list", conn):
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
        print("  - Table 'ban_list' created.")  # noqa: T201 Intentional print for feedback
    else:
        print("  - Table 'ban_list' already exists.")  # noqa: T201 Intentional print for feedback

    # Data Migrations
    if _table_exists("user_settings", conn) and _column_exists("user_settings", "muted_users", conn):
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
                    users_to_insert.append(
                        {"muted_teamtalk_username": username, "user_settings_telegram_id": telegram_id}
                    )
        if users_to_insert:
            op.bulk_insert(muted_users_table_ref, users_to_insert)
        with op.batch_alter_table("user_settings", schema=None) as batch_op:
            batch_op.drop_column("muted_users")
    else:
        pass

    if _table_exists("user_settings", conn):
        if _column_exists("user_settings", "mute_all", conn):
            if not _column_exists("user_settings", "mute_list_mode", conn):
                with op.batch_alter_table("user_settings", schema=None) as batch_op:
                    batch_op.add_column(
                        sa.Column("mute_list_mode", sa.String(), nullable=False, server_default="blacklist")
                    )
            user_settings_table_for_mute_all = sa.Table(
                "user_settings",
                sa.MetaData(),
                sa.Column("telegram_id", sa.Integer, primary_key=True),
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
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.drop_column("mute_all")
        elif not _column_exists("user_settings", "mute_list_mode", conn):
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("mute_list_mode", sa.String(), nullable=False, server_default="blacklist")
                )
        else:
            pass

    if _table_exists("user_settings", conn):
        if _column_exists("user_settings", "language", conn) and not _column_exists(
            "user_settings", "language_code", conn
        ):
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.alter_column("language", new_column_name="language_code", existing_type=sa.String())
        elif not _column_exists("user_settings", "language_code", conn):
            with op.batch_alter_table("user_settings", schema=None) as batch_op:
                batch_op.add_column(sa.Column("language_code", sa.String(), nullable=False, server_default="en"))
        else:
            pass


def downgrade() -> None:
    """
    This function rolls back the changes, returning the schema to the 'master' branch state.
    Useful for testing or in case of problems.
    """
    op.drop_index(op.f("ix_ban_list_teamtalk_username"), table_name="ban_list")
    op.drop_index(op.f("ix_ban_list_telegram_id"), table_name="ban_list")
    op.drop_table("ban_list")

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.alter_column("language_code", new_column_name="language", existing_type=sa.String())

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mute_all", sa.Boolean(), nullable=False, server_default=sa.false()))

    user_settings_table_ref = table(
        "user_settings", column("mute_all", sa.Boolean), column("mute_list_mode", sa.String)
    )
    conn = op.get_bind()
    conn.execute(
        user_settings_table_ref.update()
        .where(user_settings_table_ref.c.mute_list_mode == "whitelist")
        .values(mute_all=True)
    )
    conn.execute(
        user_settings_table_ref.update()
        .where(user_settings_table_ref.c.mute_list_mode == "blacklist")
        .values(mute_all=False)
    )

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("mute_list_mode")

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("muted_users", sa.VARCHAR(), nullable=False, server_default=""))

    conn = op.get_bind()
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

    op.drop_index(op.f("ix_muted_users_muted_teamtalk_username"), table_name="muted_users")
    op.drop_table("muted_users")
