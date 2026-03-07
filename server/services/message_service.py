from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import logging

from server.crypto.hybrid import HybridEncryption
from server.database import get_db
from server.database.Messages import Messages
from server.database.Users import Users
from server.database.UserKeys import UserKeys
from server.services.notification_service import NotificationService
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class MessageService:
    """Сервис для обработки сообщений с кросс-доставкой"""

    @staticmethod
    async def send_message(
        sender_id: uuid.UUID,
        recipient_id: uuid.UUID,
        message_data: Dict[str, Any],
        encrypted_data: str,
        encrypted_aes_key: str,
        nonce: str,
        signature: Optional[str],
        room_id: Optional[uuid.UUID],
        db: Session
    ) -> Messages:
        """
        Отправка сообщения (REST или WebSocket)

        Args:
            sender_id: ID отправителя
            recipient_id: ID получателя
            message_data: Исходные данные сообщения
            encrypted_data: Зашифрованные данные (Base64)
            encrypted_aes_key: Зашифрованный AES ключ (Base64)
            nonce: Nonce для AES-GCM (Base64)
            signature: Цифровая подпись (опционально)
            room_id: ID комнаты (для групповых чатов)
            db: Сессия БД

        Returns:
            Созданное сообщение
        """
        # Проверяем существование получателя
        recipient = db.query(Users).filter(Users.id == recipient_id).first()
        if not recipient:
            raise ValueError(f"Recipient {recipient_id} not found")

        # Создаем запись сообщения
        message = Messages(
            sender_id=sender_id,
            recipient_id=recipient_id,
            room_id=room_id,
            encrypted_data=encrypted_data,
            encrypted_aes_key=encrypted_aes_key,
            nonce=nonce,
            signature=signature,
            message_type="direct" if not room_id else "group",
            is_read=False,
            is_delivered=False,
            sent_at=datetime.utcnow()
        )

        db.add(message)
        db.commit()
        db.refresh(message)

        logger.info(f"Message {message.id} saved from {sender_id} to {recipient_id}")

        # Отправляем уведомление получателю
        await NotificationService.notify_new_message(
            message_id=message.id,
            sender_id=sender_id,
            recipient_id=recipient_id,
            room_id=room_id,
            encrypted_data=encrypted_data,
            sent_at=message.sent_at
        )

        return message

    @staticmethod
    def get_messages(
        user_id: uuid.UUID,
        db: Session,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False
    ) -> list[Messages]:
        """
        Получение сообщений для пользователя

        Args:
            user_id: ID пользователя
            db: Сессия БД
            limit: Лимит сообщений
            offset: Сдвиг
            unread_only: Только непрочитанные

        Returns:
            Список сообщений
        """
        query = db.query(Messages).filter(
            (Messages.recipient_id == user_id) | (Messages.room_id.isnot(None))
        )

        if unread_only:
            query = query.filter(Messages.is_read == False)

        messages = query.order_by(Messages.sent_at.desc()).limit(limit).offset(offset).all()

        return messages

    @staticmethod
    def mark_as_read(message_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> bool:
        """Пометить сообщение как прочитанное"""
        message = db.query(Messages).filter(
            Messages.id == message_id,
            Messages.recipient_id == user_id
        ).first()

        if not message:
            return False

        message.is_read = True
        message.read_at = datetime.utcnow()
        db.commit()

        return True

    @staticmethod
    def get_message(message_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> Optional[Messages]:
        """Получить конкретное сообщение"""
        message = db.query(Messages).filter(
            Messages.id == message_id,
            (Messages.sender_id == user_id) | (Messages.recipient_id == user_id)
        ).first()

        return message


# Глобальный экземпляр
message_service = MessageService()
