-- Вложения: ciphertext в БД (BYTEA). Ключи — только внутри зашифрованного сообщения.

CREATE TABLE IF NOT EXISTS attachments (
    id UUID PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    uploaded_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    variant VARCHAR(20) NOT NULL,
    parent_attachment_id UUID REFERENCES attachments(id) ON DELETE CASCADE,
    original_filename VARCHAR(512) NOT NULL DEFAULT 'file',
    content_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    ciphertext BYTEA NOT NULL,
    index_date TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_attachments_room_id ON attachments (room_id);
CREATE INDEX IF NOT EXISTS ix_attachments_uploaded_by ON attachments (uploaded_by);
CREATE INDEX IF NOT EXISTS ix_attachments_parent_attachment_id ON attachments (parent_attachment_id);
