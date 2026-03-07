from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, Boolean, DateTime, ForeignKey, UUID
from datetime import datetime
import uuid


class UserKeys(BaseModel):
    """Модель для хранения криптографических ключей пользователей"""
    __tablename__ = "user_keys"

    # Связь с пользователем
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # Ключи
    public_key = Column(Text, nullable=False)  # Публичный ключ (PEM format)
    private_key_encrypted = Column(Text, nullable=True)  # Зашифрованный приватный ключ

    # Метаданные ключа
    key_type = Column(String(50), default="RSA-4096")  # Тип ключа
    key_fingerprint = Column(String(255), unique=True, index=True)  # Отпечаток ключа
    is_active = Column(Boolean, default=True)  # Текущий ли ключ

    # Сроки действия
    expires_at = Column(DateTime(timezone=True), nullable=True)
    rotated_at = Column(DateTime(timezone=True), nullable=True)  # Когда был заменен
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def __repr__(self):
        return f"<UserKeys(id={self.id}, user_id={self.user_id}, key_type={self.key_type})>"
