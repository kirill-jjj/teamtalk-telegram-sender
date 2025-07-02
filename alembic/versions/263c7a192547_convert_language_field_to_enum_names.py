"""convert_language_field_to_enum_names

Revision ID: 263c7a192547
Revises: 2b8d9f4a1c7e
Create Date: 2025-07-02 06:03:22.220622

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


# revision identifiers, used by Alembic.
revision: str = '263c7a192547'
down_revision: Union[str, Sequence[str], None] = '2b8d9f4a1c7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_settings_table = table(
        'user_settings',
        column('language', sa.String)
    )

    op.execute(
        user_settings_table.update().
        where(user_settings_table.c.language == 'en').
        values(language='ENGLISH')
    )
    op.execute(
        user_settings_table.update().
        where(user_settings_table.c.language == 'ru').
        values(language='RUSSIAN')
    )


def downgrade() -> None:
    user_settings_table = table(
        'user_settings',
        column('language', sa.String)
    )

    op.execute(
        user_settings_table.update().
        where(user_settings_table.c.language == 'ENGLISH').
        values(language='en')
    )
    op.execute(
        user_settings_table.update().
        where(user_settings_table.c.language == 'RUSSIAN').
        values(language='ru')
    )
