-- Вариант A: групповое сообщение — одна строка messages (recipient_id NULL), прочтение — message_reads.
-- 1) recipient_id в messages становится необязательным.
-- 2) Таблица message_reads: кто прочитал групповое сообщение (пара message_id + user_id).
--
-- Выполнить один раз на существующей БД, из каталога ChatService:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/migrate_messages_variant_a_message_reads.sql
--
-- Docker + bash (stdin из файла):
--   docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1 < migrations/migrate_messages_variant_a_message_reads.sql
--
-- Docker + PowerShell (в PowerShell оператор "<" из файла не работает — подайте SQL через pipe):
--   Get-Content .\migrations\migrate_messages_variant_a_message_reads.sql -Raw | docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1
--
-- Docker + cmd.exe на Windows:
--   cmd /c "docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1 < migrations\migrate_messages_variant_a_message_reads.sql"

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'messages'
      AND column_name = 'recipient_id'
      AND is_nullable = 'NO'
  ) THEN
    ALTER TABLE messages ALTER COLUMN recipient_id DROP NOT NULL;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS message_reads (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    message_id UUID NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_message_reads_message_user UNIQUE (message_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_message_reads_message_id ON message_reads (message_id);
CREATE INDEX IF NOT EXISTS ix_message_reads_user_id ON message_reads (user_id);

COMMENT ON TABLE message_reads IS 'Прочтение групповых сообщений (messages.recipient_id IS NULL): одна строка на пару сообщение–пользователь';
