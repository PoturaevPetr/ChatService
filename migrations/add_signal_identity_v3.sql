-- CRYPTO_DEVICES_V3.2: Signal Curve25519 identity alongside RSA hybrid
ALTER TABLE devices ADD COLUMN IF NOT EXISTS signal_identity_key_public TEXT;
