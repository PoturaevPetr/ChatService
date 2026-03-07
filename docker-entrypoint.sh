#!/bin/bash
set -e

# Функция для проверки готовности PostgreSQL
wait_for_db() {
    echo "⏳ Waiting for PostgreSQL to be ready..."
    
    host="${DB_HOST:-postgres}"
    port="${DB_PORT:-5432}"
    user="${DB_USER:-postgres}"
    db="${DB_NAME:-ChatDatabase}"
    
    until PGPASSWORD="${DB_PASSWORD:-postgres}" psql -h "$host" -p "$port" -U "$user" -d "$db" -c '\q' 2>/dev/null; do
        echo "⏳ PostgreSQL is unavailable - sleeping"
        sleep 2
    done
    
    echo "✅ PostgreSQL is ready!"
}

# Ждем готовности БД
wait_for_db

# Запускаем приложение
echo "🚀 Starting ChatService..."
exec python start.py
