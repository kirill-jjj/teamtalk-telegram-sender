"""alter_user_settings_language_to_language_code

Revision ID: 14b748191b19
Revises: 5edd5f3c3434
Create Date: 2025-07-03 08:12:56.874139

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14b748191b19'
down_revision: Union[str, Sequence[str], None] = '5edd5f3c3434'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('user_settings', 'language', new_column_name='language_code', existing_type=sa.String())
    # The default value was handled by SQLModel in the Python code.
    # If we wanted to ensure the DB default is also set, we could add server_default here,
    # but SQLModel's default on insert should suffice.
    # The nullable=False constraint should already be in place.


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('user_settings', 'language_code', new_column_name='language', existing_type=sa.String())
