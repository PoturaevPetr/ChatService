from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, DateTime, Text, UUID, Boolean
from datetime import datetime, timedelta
import uuid


class Sessions(BaseModel):
    """Модель сессий пользователей (JWT токены)"""
    __tablename__ = "sessions"

    # Пользователь
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Токен
    token_jti = Column(String(255), unique=True, nullable=False, index=True)  # JWT ID
    refresh_token = Column(String(500), nullable=True)  # Refresh токен

    # Метаданные сессии
    user_agent = Column(Text, nullable=True)  # User agent клиента
    ip_address = Column(String(50), nullable=True)  # IP адрес
    service_id = Column(String(100), nullable=False)  # ID сервиса

    # Статус
    is_revoked = Column(Boolean, default=False)  # Отозван ли токен
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # Сроки действия
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    def is_valid(self) -> bool:
        """Проверка валидности сессии"""
        if self.is_revoked:
            return False
        if datetime.utcnow() > self.expires_at:
            return False
        return True

    def revoke(self):
        """Отзыв сессии"""
        self.is_revoked = True
        self.revoked_at = datetime.utcnow()

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"
