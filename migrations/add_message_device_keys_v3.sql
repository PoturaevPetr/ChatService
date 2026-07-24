-- CRYPTO_DEVICES_V3.2: per-device message key wraps (hybrid_device_v0)
CREATE TABLE IF NOT EXISTS message_device_keys (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id VARCHAR(64) NOT NULL,
    encrypted_aes_key TEXT NOT NULL,
    CONSTRAINT uq_message_device_keys_message_device UNIQUE (message_id, device_id)
);

CREATE INDEX IF NOT EXISTS ix_message_device_keys_message_id ON message_device_keys (message_id);
CREATE INDEX IF NOT EXISTS ix_message_device_keys_user_id ON message_device_keys (user_id);
CREATE INDEX IF NOT EXISTS ix_message_device_keys_device_id ON message_device_keys (device_id);
