from server.database.BaseModel import BaseModel
from sqlalchemy import Column, UUID, ForeignKey, Text, Boolean, DateTime, String
from datetime import datetime
import uuid


class Messages(BaseModel):
    """Модель зашифрованных сообщений"""
    __tablename__ = "messages"

    # Отправитель и получатель
    sender_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    recipient_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # NULL для групповых чатов

    # Комната (для групповых чатов)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True, index=True)

    # Зашифрованные данные
    encrypted_data = Column(Text, nullable=False)  # Base64 зашифрованного сообщения
    encrypted_aes_key = Column(Text, nullable=False)  # Base64 зашифрованного AES ключа
    nonce = Column(Text, nullable=False)  # Base64 nonce для AES-GCM

    # Цифровая подпись (опционально)
    signature = Column(Text, nullable=True)  # Base64 подписи отправителя

    # Метаданные
    message_type = Column(String(50), default="direct")  # 'direct' | 'group' | 'system'
    is_read = Column(Boolean, default=False)
    is_delivered = Column(Boolean, default=False)

    # Временные метки
    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    # Исходный текст (только для отладки, в продакшене NULL)
    text = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Message(id={self.id}, sender={self.sender_id}, recipient={self.recipient_id})>"