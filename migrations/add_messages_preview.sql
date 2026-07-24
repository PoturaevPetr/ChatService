-- Превью сообщений без медиа (для быстрой загрузки списка).
-- Выполнить один раз: psql ... -f migrations/add_messages_preview.sql

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS encrypted_preview TEXT,
ADD COLUMN IF NOT EXISTS preview_nonce TEXT;

COMMENT ON COLUMN messages.encrypted_preview IS 'Encrypted preview (text + has_attachment) for list view';
COMMENT ON COLUMN messages.preview_nonce IS 'Nonce for encrypted_preview';
