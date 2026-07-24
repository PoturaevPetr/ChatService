from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, DateTime, Text, UUID, Boolean
from datetime import datetime, timezone


class Sessions(BaseModel):
    """Модель сессий пользователей (JWT токены)"""
    __tablename__ = "sessions"

    # Пользователь
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Токен
    token_jti = Column(String(255), unique=True, nullable=False, index=True)
    refresh_token = Column(String(500), nullable=True)

    # Метаданные сессии
    user_agent = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    service_id = Column(String(100), nullable=False)

    # Статус
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    # Сроки действия
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def is_valid(self) -> bool:
        """Проверка валидности сессии"""
        try:
            if self.is_revoked:
                print(f"Session {self.id} is revoked")
                return False

            expires_at = self.expires_at
            if expires_at is None:
                return False
            # Normalize naive timestamps from legacy rows.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            current_time = datetime.now(timezone.utc)
            if current_time > expires_at:
                print(f"Session {self.id} expired at {expires_at}, current time {current_time}")
                return False

            return True
        except Exception as e:
            print(f"Error in is_valid for session {self.id}: {str(e)}")
            return False

    def revoke(self):
        """Отзыв сессии"""
        self.is_revoked = True
        self.revoked_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"