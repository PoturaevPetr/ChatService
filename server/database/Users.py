from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, Text, Boolean, DateTime, Date
from datetime import datetime
import uuid
from sqlalchemy.orm import relationship

class Users(BaseModel):
    """Модель пользователей"""
    __tablename__ = "users"

    # Основные поля
    username = Column(String(100), unique=True, nullable=False, index=True)
    service_id = Column(String(100), nullable=False, index=True)

    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    middle_name = Column(String, nullable=True)
    birth_date = Column(Date, nullable=True)
    # Храним data URL base64, поэтому нужен TEXT (VARCHAR(255) легко не влезет).
    avatar = Column(Text, nullable=True)

    # bcrypt / bcrypt_sha256 (passlib); длина хэша может превышать 60 символов.
    password_hash = Column(String(512), nullable=True)

    # Статус
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    llm_enabled = Column(Boolean, default=False, nullable=False)

    # Метаданные
    last_login = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    rooms_relations = relationship("RoomUsers", back_populates="user", cascade="all, delete-orphan")
    created_rooms = relationship("Rooms", foreign_keys="Rooms.created_by", back_populates="creator")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, service_id={self.service_id})>"
