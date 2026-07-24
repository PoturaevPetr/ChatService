from server.database.BaseModel import BaseModel
from sqlalchemy import Column, UUID, ForeignKey, Text, Boolean, DateTime, String, Index
from datetime import datetime
import uuid


class Messages(BaseModel):
    """Модель зашифрованных сообщений"""
    __tablename__ = "messages"

    __table_args__ = (
        # Лента комнаты ORDER BY sent_at: см. migrations/add_performance_indexes.sql на уже существующих БД
        Index("ix_messages_room_id_sent_at", "room_id", "sent_at"),
    )

    # Отправитель и получатель
    sender_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    recipient_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # NULL: вариант A (группа), одна строка messages

    # Комната (для групповых чатов); одиночный индекс по room_id не нужен — покрывает составной ix_messages_room_id_sent_at
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True)

    # Одно тело сообщения (AES), ключ расшифровки — в MessageRecipientKeys по user_id
    encrypted_data = Column(Text, nullable=False)  # Base64
    nonce = Column(Text, nullable=False)  # Base64 nonce для AES-GCM
    encrypted_aes_key = Column(Text, nullable=True)  # устаревшее, для старых записей; новые используют message_recipient_keys

    # Цифровая подпись (опционально)
    signature = Column(Text, nullable=True)  # Base64 подписи отправителя

    # Метаданные
    message_type = Column(String(50), default="direct")  # 'direct' | 'group' | 'system'
    status = Column(String(20), default="sent")  # pending | sent | delivered | read | failed
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