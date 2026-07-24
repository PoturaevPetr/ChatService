-- Добавление поля status в таблицу messages (статус отправки/доставки).
-- Значения: pending, sent, delivered, read, failed.
-- Выполнить один раз на существующей БД: psql ... -f migrations/add_messages_status.sql

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'sent';

COMMENT ON COLUMN messages.status IS 'pending|sent|delivered|read|failed';
