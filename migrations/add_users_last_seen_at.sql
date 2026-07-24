-- Время последней активности пользователя в приложении (обновляется при WS connect / полном disconnect).
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN users.last_seen_at IS 'Последний раз замечен онлайн (UTC); для отображения «был в сети».';
