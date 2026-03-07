from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Integer, UUID
from datetime import datetime
import uuid
from sqlalchemy.orm import relationship


class Rooms(BaseModel):
    """Модель комнат (групповых чатов)"""
    __tablename__ = "rooms"

    # Основная информация
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Создатель - ИСПРАВЛЕНО (добавлен ForeignKey)
    created_by = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="SET NULL"),  # Добавлен ForeignKey
        nullable=False, 
        index=True
    )

    # Тип комнаты
    room_type = Column(String(50), default="group")  # 'group' | 'channel' | 'support'

    # Статус
    is_active = Column(Boolean, default=True)

    # Метаданные
    participant_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    participants = relationship("RoomUsers", back_populates="room", cascade="all, delete-orphan")
    
    # Для прямого доступа к пользователям
    users = relationship(
        "Users", 
        secondary="room_user", 
        viewonly=True,
        primaryjoin="Rooms.id == RoomUsers.room_id",
        secondaryjoin="RoomUsers.user_id == Users.id"
    )
    
    # Создатель комнаты - ИСПРАВЛЕНО (User -> Users)
    creator = relationship("Users", foreign_keys=[created_by], back_populates="created_rooms")

    def __repr__(self):
        return f"<Room(id={self.id}, name={self.name}, type={self.room_type})>"