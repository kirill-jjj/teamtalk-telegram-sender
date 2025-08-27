# Этап 1: Сборка и установка зависимостей
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем системные зависимости, необходимые для распаковки SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

# Устанавливаем uv
RUN pip install uv

# Копируем pyproject.toml и устанавливаем зависимости
COPY pyproject.toml ./
RUN uv sync --all-extras

# Устанавливаем SDK, запуская Python через uv, чтобы он видел зависимости
RUN uv run python -c "import pytalk"

# Этап 2: Финальный образ
FROM python:3.11-slim

WORKDIR /app

# Копируем установленные зависимости, включая pytalk и его SDK, из .venv билдера
# в глобальный site-packages финального образа
COPY --from=builder /app/.venv/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/

# Копируем исполняемые файлы, созданные uv (например, 'sender', 'i18n')
COPY --from=builder /app/.venv/bin/ /usr/local/bin/

# Копируем остальные файлы приложения
COPY . .

# Компилируем файлы локализации. 'i18n' теперь доступен глобально.
RUN i18n compile

# Указываем команду для запуска приложения.
# Запускаем 'sender' напрямую, так как он теперь в /usr/local/bin/
CMD ["sender", "--config", "config.toml"]
