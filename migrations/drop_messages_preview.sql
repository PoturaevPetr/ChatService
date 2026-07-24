-- Удаление колонок превью: превью делается на клиенте, серверу не нужны.
-- Выполнить один раз: psql ... -f migrations/drop_messages_preview.sql

ALTER TABLE messages
DROP COLUMN IF EXISTS encrypted_preview,
DROP COLUMN IF EXISTS preview_nonce;
