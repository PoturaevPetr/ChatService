FROM python:3.10-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Устанавливаем psycopg2-binary
RUN pip install --no-cache-dir psycopg2-binary==2.9.9

# Создаем директорию для БД
RUN mkdir -p /data

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PORT=8320

# Открываем порт
EXPOSE 8320

# Запускаем приложение
CMD ["python", "start.py"]
