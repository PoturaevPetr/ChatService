-- Индексы под типичные запросы чата (membership, лента по комнате, личные по recipient).
-- Идемпотентно: безопасно гонять повторно.
-- Применение: make migrate-performance-indexes (или psql -f ...)

-- room_user: участники комнаты и «комнаты пользователя»
CREATE INDEX IF NOT EXISTS ix_room_user_room_id ON room_user (room_id);
CREATE INDEX IF NOT EXISTS ix_room_user_user_id ON room_user (user_id);

-- messages: лента по комнате с сортировкой по времени (частично дублирует одиночный room_id, но даёт лучший план для ORDER BY sent_at)
CREATE INDEX IF NOT EXISTS ix_messages_room_id_sent_at ON messages (room_id, sent_at DESC);

-- Личные сообщения по получателю + время (recipient_id IS NULL у групповых строк)
CREATE INDEX IF NOT EXISTS ix_messages_recipient_id_sent_at
  ON messages (recipient_id, sent_at DESC)
  WHERE recipient_id IS NOT NULL;
