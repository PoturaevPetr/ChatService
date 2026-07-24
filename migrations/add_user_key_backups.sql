-- Greenfield: passphrase-encrypted key backup (private никогда не на сервере)
CREATE TABLE IF NOT EXISTS user_key_backups (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ciphertext TEXT NOT NULL,
    kdf VARCHAR(64) NOT NULL DEFAULT 'pbkdf2-sha256',
    kdf_salt_b64 TEXT NOT NULL,
    kdf_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    wrap_alg VARCHAR(64) NOT NULL DEFAULT 'aes-256-gcm',
    nonce_b64 TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_key_backups_user_id UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS ix_user_key_backups_user_id ON user_key_backups (user_id);

-- Убрать legacy-колонки, если поднимали старую схему (таблица user_keys могла быть удалена в V3.5)
ALTER TABLE users DROP COLUMN IF EXISTS keys_migrated_v2;
ALTER TABLE attachments DROP COLUMN IF EXISTS server_decrypt_key_b64;
ALTER TABLE attachments DROP COLUMN IF EXISTS server_decrypt_nonce_b64;
