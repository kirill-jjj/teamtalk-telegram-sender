"""unify_master_to_refactor_schema

Revision ID: 1a2b3c4d5e6f
Revises:
Create Date: 2025-07-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    This function updates the database schema from the 'master' branch state
    to the 'refactor' branch state, preserving all data.
    """
    print("Starting upgrade from 'master' schema to 'refactor' schema...")

    # --- Change 1: Convert `muted_users` (string) to a separate `MutedUser` table ---
    print("Step 1/5: Converting muted_users string to a dedicated MutedUser table...")
    # 1.1. Create a new table `muted_users`
    muted_users_table = op.create_table('muted_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('muted_teamtalk_username', sa.String(), nullable=False),
        sa.Column('user_settings_telegram_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_settings_telegram_id'], ['user_settings.telegram_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_muted_users_muted_teamtalk_username'), 'muted_users', ['muted_teamtalk_username'], unique=False)
    print("  - Table 'muted_users' created.")

    # 1.2. Migrate data from the old `muted_users` column to the new table
    conn = op.get_bind()
    results = conn.execute(sa.text("SELECT telegram_id, muted_users FROM user_settings")).fetchall()
    users_to_insert = []
    for telegram_id, muted_users_str in results:
        if muted_users_str and muted_users_str.strip():
            usernames = [name.strip() for name in muted_users_str.split(',') if name.strip()]
            for username in usernames:
                users_to_insert.append({
                    'muted_teamtalk_username': username,
                    'user_settings_telegram_id': telegram_id
                })

    if users_to_insert:
        op.bulk_insert(muted_users_table, users_to_insert)
        print(f"  - Migrated {len(users_to_insert)} muted user entries.")

    # 1.3. Drop the old `muted_users` column, using batch mode for SQLite
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('muted_users')
    print("  - Dropped old 'muted_users' column from 'user_settings'.")


    # --- Change 2: Replace `mute_all` (bool) with `mute_list_mode` (string) ---
    print("Step 2/5: Replacing 'mute_all' boolean with 'mute_list_mode' string...")
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mute_list_mode', sa.String(), nullable=False, server_default='blacklist'))
    print("  - Added 'mute_list_mode' column.")

    user_settings_table_ref = table('user_settings',
        column('mute_all', sa.Boolean),
        column('mute_list_mode', sa.String)
    )
    op.execute(
        user_settings_table_ref.update().
        where(user_settings_table_ref.c.mute_all == True).
        values(mute_list_mode='whitelist')
    )
    op.execute(
        user_settings_table_ref.update().
        where(user_settings_table_ref.c.mute_all == False).
        values(mute_list_mode='blacklist')
    )
    print("  - Migrated data from 'mute_all' to 'mute_list_mode'.")

    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('mute_all')
    print("  - Dropped old 'mute_all' column.")


    # --- Change 3: Rename `language` column to `language_code` ---
    print("Step 3/5: Renaming 'language' column to 'language_code'...")
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.alter_column('language', new_column_name='language_code', existing_type=sa.String())
    print("  - Column renamed.")


    # --- Change 4: Create new `BanList` table ---
    print("Step 4/5: Creating 'ban_list' table...")
    op.create_table('ban_list',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.Integer(), nullable=True),
        sa.Column('teamtalk_username', sa.String(), nullable=True),
        sa.Column('ban_reason', sa.String(), nullable=True),
        sa.Column('banned_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ban_list_telegram_id'), 'ban_list', ['telegram_id'], unique=False)
    op.create_index(op.f('ix_ban_list_teamtalk_username'), 'ban_list', ['teamtalk_username'], unique=False)
    print("  - Table 'ban_list' created.")

    print("Step 5/5: Finalizing schema changes...")
    print("✅ Upgrade to 'refactor' schema complete.")


def downgrade() -> None:
    """
    This function rolls back the changes, returning the schema to the 'master' branch state.
    Useful for testing or in case of problems.
    """
    print("Starting downgrade from 'refactor' schema to 'master' schema...")

    # --- Rollback 4: Drop `BanList` table ---
    print("Step 1/4: Dropping 'ban_list' table...")
    op.drop_index(op.f('ix_ban_list_teamtalk_username'), table_name='ban_list')
    op.drop_index(op.f('ix_ban_list_telegram_id'), table_name='ban_list')
    op.drop_table('ban_list')
    print("  - Table 'ban_list' dropped.")

    # --- Rollback 3: Rename `language_code` back to `language` ---
    print("Step 2/4: Renaming 'language_code' back to 'language'...")
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.alter_column('language_code', new_column_name='language', existing_type=sa.String())
    print("  - Column renamed.")

    # --- Rollback 2: Revert `mute_list_mode` to `mute_all` ---
    print("Step 3/4: Reverting 'mute_list_mode' to 'mute_all'...")
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mute_all', sa.BOOLEAN(), nullable=False, server_default=sa.false()))
    print("  - Added back 'mute_all' column.")

    user_settings_table_ref = table('user_settings',
        column('mute_all', sa.Boolean),
        column('mute_list_mode', sa.String)
    )
    op.execute(
        user_settings_table_ref.update().
        where(user_settings_table_ref.c.mute_list_mode == 'whitelist').
        values(mute_all=True)
    )
    op.execute(
        user_settings_table_ref.update().
        where(user_settings_table_ref.c.mute_list_mode == 'blacklist').
        values(mute_all=False)
    )
    print("  - Migrated data from 'mute_list_mode' back to 'mute_all'.")

    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('mute_list_mode')
    print("  - Dropped 'mute_list_mode' column.")

    # --- Rollback 1: Revert MutedUser table to 'muted_users' string ---
    print("Step 4/4: Reverting MutedUser table to 'muted_users' string...")
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('muted_users', sa.VARCHAR(), nullable=False, server_default=''))
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

    op.drop_index(op.f('ix_muted_users_muted_teamtalk_username'), table_name='muted_users')
    op.drop_table('muted_users')
    print("  - Dropped 'muted_users' table.")

    print("✅ Downgrade to 'master' schema complete.")
