"""add_check_constraint_to_ban_list

Revision ID: 8f587c1b4f53
Revises: 8677509804ef
Create Date: 2024-07-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f587c1b4f53'
down_revision: Union[str, Sequence[str], None] = '8677509804ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    print(f"Applying upgrade: Add check constraint ck_ban_list_identifier_not_both_null to ban_list table")
    with op.batch_alter_table('ban_list', schema=None) as batch_op:
        batch_op.create_check_constraint(
            constraint_name='ck_ban_list_identifier_not_both_null',
            condition='telegram_id IS NOT NULL OR teamtalk_username IS NOT NULL'
        )
    print(f"Check constraint ck_ban_list_identifier_not_both_null added to ban_list table.")


def downgrade() -> None:
    print(f"Applying downgrade: Drop check constraint ck_ban_list_identifier_not_both_null from ban_list table")
    with op.batch_alter_table('ban_list', schema=None) as batch_op:
        batch_op.drop_constraint(
            constraint_name='ck_ban_list_identifier_not_both_null',
            type_='check'
        )
    print(f"Check constraint ck_ban_list_identifier_not_both_null dropped from ban_list table.")
