from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, Text, Boolean, DateTime
from datetime import datetime
import uuid


class APIKeys(BaseModel):
    """Модель API ключей для сервисов"""
    __tablename__ = "api_keys"

    # Идентификатор сервиса
    service_id = Column(String(100), nullable=False, index=True)

    # Хеши ключей (никогда не храним ключи в открытом виде)
    key_hash = Column(String(255), unique=True, nullable=False, index=True)
    secret_hash = Column(String(255), nullable=False)

    # Метаданные
    name = Column(String(255), nullable=False)
    permissions = Column(Text, nullable=True)  # JSON строка с правами

    # Статус
    is_active = Column(Boolean, default=True)

    # Сроки действия
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def __repr__(self):
        return f"<APIKey(id={self.id}, service_id={self.service_id}, name={self.name})>"
