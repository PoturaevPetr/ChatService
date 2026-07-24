-- Реакции эмодзи на сообщения (не E2E: только разрешённые эмодзи + участник комнаты).

CREATE TABLE IF NOT EXISTS message_reactions (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    emoji TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    CONSTRAINT message_reactions_one_per_user UNIQUE (message_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_message_reactions_message_id ON message_reactions (message_id);
CREATE INDEX IF NOT EXISTS ix_message_reactions_room_id ON message_reactions (room_id);
