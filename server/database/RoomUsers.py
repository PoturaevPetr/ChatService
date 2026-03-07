from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, Integer, UUID
from datetime import datetime
from sqlalchemy.orm import relationship
import uuid

class RoomUsers(BaseModel):
    __tablename__ = "room_user"
    
    
    # Внешние ключи
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    
    # Дополнительные поля для связи
    joined_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    role = Column(String(50), default="member")  # 'admin', 'member', 'moderator'
    
    # Relationships - ИСПРАВЛЕНО
    room = relationship("Rooms", back_populates="participants")
    user = relationship("Users", back_populates="rooms_relations")  # Изменено с "rooms" на "rooms_relations"

    def __repr__(self):
        return f"<RoomUser(user_id={self.user_id}, room_id={self.room_id}, role={self.role})>"



