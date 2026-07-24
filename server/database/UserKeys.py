from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, Boolean, DateTime, ForeignKey, UUID
from datetime import datetime


class UserKeys(BaseModel):
    """Публичные ключи пользователей (private только на клиенте)."""
    __tablename__ = "user_keys"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    public_key = Column(Text, nullable=False)  # PEM SubjectPublicKeyInfo
    key_type = Column(String(50), default="RSA-4096")
    key_fingerprint = Column(String(255), unique=True, index=True)
    is_active = Column(Boolean, default=True)

    expires_at = Column(DateTime(timezone=True), nullable=True)
    rotated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def __repr__(self):
        return f"<UserKeys(id={self.id}, user_id={self.user_id}, key_type={self.key_type})>"
