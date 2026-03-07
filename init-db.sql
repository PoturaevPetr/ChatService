-- Инициализация базы данных ChatService
-- Этот скрипт выполняется автоматически при первом запуске контейнера PostgreSQL

-- Убедимся, что база данных существует
-- (она уже создана через переменную POSTGRES_DB)

-- Создаем расширение для UUID (если его нет)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Выводим информацию
DO $$
BEGIN
    RAISE NOTICE 'ChatDatabase initialized successfully!';
    RAISE NOTICE 'UUID extension is enabled';
END $$;
