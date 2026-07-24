-- CRYPTO_DEVICES_V3: per-device identity + one-time prekeys
CREATE TABLE IF NOT EXISTS devices (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id VARCHAR(64) NOT NULL,
    name VARCHAR(255),
    platform VARCHAR(32) NOT NULL DEFAULT 'web',
    identity_key_public TEXT NOT NULL,
    registration_id INTEGER NOT NULL DEFAULT 0,
    signed_prekey_id INTEGER,
    signed_prekey_public TEXT,
    signed_prekey_signature TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    CONSTRAINT uq_devices_user_device UNIQUE (user_id, device_id)
);

CREATE INDEX IF NOT EXISTS ix_devices_user_id ON devices (user_id);
CREATE INDEX IF NOT EXISTS ix_devices_device_id ON devices (device_id);

CREATE TABLE IF NOT EXISTS device_one_time_prekeys (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    device_row_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    key_id INTEGER NOT NULL,
    public_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMPTZ,
    CONSTRAINT uq_otpk_device_key_id UNIQUE (device_row_id, key_id)
);

CREATE INDEX IF NOT EXISTS ix_device_one_time_prekeys_device_row_id
    ON device_one_time_prekeys (device_row_id);
