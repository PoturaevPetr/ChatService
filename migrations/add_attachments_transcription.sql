-- Транскрибация вложений (однократно на существующей БД PostgreSQL)
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS transcription_text TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS transcription_status VARCHAR(20);
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS transcription_error TEXT;
