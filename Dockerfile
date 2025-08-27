# Этап 1: Сборка и установка зависимостей
FROM python:3.11-slim as builder

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем uv
RUN pip install uv

# Копируем файлы зависимостей и устанавливаем их
# Это кэшируется Docker, если файлы не меняются
COPY pyproject.toml ./
RUN uv sync --all-extras

# Этап 2: Финальный образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

# Копируем установленные зависимости из этапа сборки
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Копируем остальные файлы приложения
COPY . .

# Компилируем файлы локализации
RUN uv run i18n compile

# Указываем команду для запуска приложения
# Мы предполагаем, что config.toml будет предоставлен во время выполнения
CMD ["uv", "run", "sender", "--config", "config.toml"]
