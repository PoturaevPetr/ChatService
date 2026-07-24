-- Если таблица была создана со столбцом storage_relpath (файлы на диске), перейти на ciphertext.
-- ВНИМАНИЕ: данные с диска в БД автоматически не переносятся — старые вложения станут недоступны.

ALTER TABLE attachments ADD COLUMN IF NOT EXISTS ciphertext BYTEA;
UPDATE attachments SET ciphertext = '\x' WHERE ciphertext IS NULL;
ALTER TABLE attachments ALTER COLUMN ciphertext SET NOT NULL;
ALTER TABLE attachments DROP COLUMN IF EXISTS storage_relpath;
