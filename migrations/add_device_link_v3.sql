-- CRYPTO_DEVICES_V3.3: device linking + OTP count helper columns
ALTER TABLE devices ADD COLUMN IF NOT EXISTS linked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS device_link_challenges (
    id UUID PRIMARY KEY,
    index_date TIMESTAMPTZ,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code VARCHAR(16) NOT NULL,
    created_by_device_id VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_by_device_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_device_link_challenges_user_id ON device_link_challenges (user_id);
CREATE INDEX IF NOT EXISTS ix_device_link_challenges_code ON device_link_challenges (code);
