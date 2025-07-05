"""create_muted_users_table

Revision ID: 91f46462bb8e
Revises: 61f624ff8654
Create Date: 2025-06-30 06:29:54.836533

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column # Импортируем для работы с данными


# revision identifiers, used by Alembic.
revision: str = '91f46462bb8e'
down_revision: Union[str, Sequence[str], None] = '61f624ff8654'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### Шаг 1: Создаем новую таблицу (как и было) ###
    muted_users_table = op.create_table('muted_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('muted_teamtalk_username', sa.String(), nullable=False),
        sa.Column('user_settings_telegram_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_settings_telegram_id'], ['user_settings.telegram_id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_muted_users_muted_teamtalk_username'), 'muted_users', ['muted_teamtalk_username'], unique=False)

    # ### Шаг 2: Миграция данных из старого столбца в новую таблицу ###

    # Получаем доступ к текущему соединению с базой данных
    conn = op.get_bind()

    # Выбираем всех пользователей и их старые списки мьютов из user_settings
    results = conn.execute(sa.text("SELECT telegram_id, muted_users FROM user_settings")).fetchall()

    users_to_insert = []
    # Проходим по каждой строке из user_settings
    for telegram_id, muted_users_str in results:
        # Если строка не пустая
        if muted_users_str and muted_users_str.strip():
            # Разделяем строку по запятым на список никнеймов
            usernames = [name.strip() for name in muted_users_str.split(',') if name.strip()]
            # Для каждого никнейма готовим запись для вставки в новую таблицу
            for username in usernames:
                users_to_insert.append({
                    'muted_teamtalk_username': username,
                    'user_settings_telegram_id': telegram_id
                })

    # Если есть что вставлять, делаем это одной операцией (bulk_insert)
    if users_to_insert:
        op.bulk_insert(muted_users_table, users_to_insert)

    # ### Шаг 3: Только теперь, когда данные перенесены, удаляем старый столбец ###
    op.drop_column('user_settings', 'muted_users')


def downgrade() -> None:
    """Downgrade schema."""
    # Downgrade тоже нужно исправить, чтобы он мог восстановить данные.
    # Он должен будет сделать обратную операцию.

    # ### Шаг 1: Восстанавливаем старый столбец ###
    op.add_column('user_settings', sa.Column('muted_users', sa.VARCHAR(), nullable=False, server_default=''))

    # ### Шаг 2: Миграция данных обратно из таблицы в строку ###
    conn = op.get_bind()

    # Собираем все ники для каждого пользователя
    # Используем GROUP_CONCAT в SQLite для объединения строк
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

    # ### Шаг 3: Удаляем новую таблицу ###
    op.drop_index(op.f('ix_muted_users_muted_teamtalk_username'), table_name='muted_users')
    op.drop_table('muted_users')
