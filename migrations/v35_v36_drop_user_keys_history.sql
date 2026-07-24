-- V3.6 encrypted history sync + drop user_keys
CREATE TABLE IF NOT EXISTS encrypted_history_blobs (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_device_id VARCHAR(64) NOT NULL,
    ciphertext TEXT NOT NULL,
    nonce_b64 TEXT NOT NULL,
    meta_json TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_encrypted_history_blobs_user_id ON encrypted_history_blobs (user_id);

DROP TABLE IF EXISTS user_keys CASCADE;
