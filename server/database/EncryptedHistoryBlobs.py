"""Opaque encrypted history blobs for new-device sync (CRYPTO_DEVICES_V3.6)."""

from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, DateTime, ForeignKey, UUID, Integer
from datetime import datetime, timezone


class EncryptedHistoryBlobs(BaseModel):
    __tablename__ = "encrypted_history_blobs"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Device that uploaded the pack
    source_device_id = Column(String(64), nullable=False)
    # Opaque client ciphertext (server never decrypts)
    ciphertext = Column(Text, nullable=False)
    nonce_b64 = Column(Text, nullable=False)
    meta_json = Column(Text, nullable=True)  # room_ids, message count, etc. (non-sensitive)
    byte_size = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
