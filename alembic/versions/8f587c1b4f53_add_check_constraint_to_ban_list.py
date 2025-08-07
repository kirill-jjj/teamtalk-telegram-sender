"""add_check_constraint_to_ban_list

Revision ID: 8f587c1b4f53
Revises: 8677509804ef
Create Date: 2024-07-10 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f587c1b4f53"
down_revision: str | Sequence[str] | None = "8677509804ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ban_list", schema=None) as batch_op:
        batch_op.create_check_constraint(
            constraint_name="ck_ban_list_identifier_not_both_null",
            condition="telegram_id IS NOT NULL OR teamtalk_username IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ban_list", schema=None) as batch_op:
        batch_op.drop_constraint(
            constraint_name="ck_ban_list_identifier_not_both_null", type_="check"
        )
