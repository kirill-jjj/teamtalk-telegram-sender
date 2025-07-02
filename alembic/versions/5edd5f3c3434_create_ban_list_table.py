"""create_ban_list_table

Revision ID: 5edd5f3c3434
Revises: 263c7a192547
Create Date: 2025-07-02 11:41:14.167272

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5edd5f3c3434'
down_revision: Union[str, Sequence[str], None] = '263c7a192547'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_ban_list_teamtalk_username'), table_name='ban_list')
    op.drop_index(op.f('ix_ban_list_telegram_id'), table_name='ban_list')
    op.drop_table('ban_list')
