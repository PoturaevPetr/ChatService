from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, DateTime, ForeignKey, UUID, JSON
from datetime import datetime
import uuid


class UserKeyBackups(BaseModel):
    """Passphrase-encrypted private key blob (сервер не знает passphrase)."""

    __tablename__ = "user_key_backups"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    ciphertext = Column(Text, nullable=False)
    kdf = Column(String(64), nullable=False, default="pbkdf2-sha256")
    kdf_salt_b64 = Column(Text, nullable=False)
    kdf_params = Column(JSON, nullable=False, default=dict)
    wrap_alg = Column(String(64), nullable=False, default="aes-256-gcm")
    nonce_b64 = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserKeyBackups(id={self.id}, user_id={self.user_id})>"
