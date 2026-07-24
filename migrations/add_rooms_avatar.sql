-- Аватар группы (data URL или URL, как у users.avatar).
-- Выполнить на существующей БД (PostgreSQL):
--   Get-Content .\migrations\add_rooms_avatar.sql -Raw | docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1

ALTER TABLE rooms ADD COLUMN IF NOT EXISTS avatar TEXT;

COMMENT ON COLUMN rooms.avatar IS 'Аватар группы (TEXT: data URL или внешний URL)';
