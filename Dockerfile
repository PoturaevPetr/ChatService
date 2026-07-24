FROM python:3.10-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости с зеркалом
COPY requirements.txt .

# Используем зеркало Aliyun (быстрее для России/Азии)
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем директорию для БД
RUN mkdir -p /data

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PORT=8320

EXPOSE 8320

CMD ["python", "start.py"]