from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import json
import logging

from server.websocket.manager import manager

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис для управления уведомлениями и доставкой сообщений"""

    @staticmethod
    async def notify_new_message(
        message_id: uuid.UUID,
        sender_id: uuid.UUID,
        recipient_id: uuid.UUID,
        room_id: Optional[uuid.UUID],
        encrypted_data: str,
        sent_at: datetime
    ):
        """
        Уведомление о новом сообщении

        Args:
            message_id: ID сообщения
            sender_id: ID отправителя
            recipient_id: ID получателя (для личных сообщений)
            room_id: ID комнаты (для групповых чатов)
            encrypted_data: Зашифрованные данные
            sent_at: Время отправки
        """
        notification = {
            "type": "new_message",
            "data": {
                "message_id": str(message_id),
                "sender_id": str(sender_id),
                "recipient_id": str(recipient_id) if recipient_id else None,
                "room_id": str(room_id) if room_id else None,
                "encrypted_data": encrypted_data,
                "sent_at": sent_at.isoformat()
            }
        }

        # Если это личное сообщение
        if recipient_id and not room_id:
            await manager.send_to_user(recipient_id, notification)
            logger.info(f"Notification sent to user {recipient_id} for message {message_id}")

        # Если это групповое сообщение
        elif room_id:
            await manager.broadcast_to_room(room_id, notification, exclude_user=sender_id)
            logger.info(f"Notification broadcasted to room {room_id} for message {message_id}")

    @staticmethod
    async def notify_message_read(message_id: uuid.UUID, reader_id: uuid.UUID, sender_id: uuid.UUID):
        """Уведомление о прочтении сообщения"""
        notification = {
            "type": "message_read",
            "data": {
                "message_id": str(message_id),
                "reader_id": str(reader_id),
                "read_at": datetime.utcnow().isoformat()
            }
        }

        await manager.send_to_user(sender_id, notification)
        logger.info(f"Read notification sent to {sender_id} for message {message_id}")

    @staticmethod
    async def notify_user_online(user_id: uuid.UUID, room_id: Optional[uuid.UUID] = None):
        """Уведомление о том, что пользователь онлайн"""
        notification = {
            "type": "user_online",
            "data": {
                "user_id": str(user_id),
                "timestamp": datetime.utcnow().isoformat()
            }
        }

        if room_id:
            await manager.broadcast_to_room(room_id, notification, exclude_user=user_id)
        else:
            await manager.broadcast_to_all(notification)

    @staticmethod
    async def notify_user_offline(user_id: uuid.UUID, room_id: Optional[uuid.UUID] = None):
        """Уведомление о том, что пользователь оффлайн"""
        notification = {
            "type": "user_offline",
            "data": {
                "user_id": str(user_id),
                "timestamp": datetime.utcnow().isoformat()
            }
        }

        if room_id:
            await manager.broadcast_to_room(room_id, notification, exclude_user=user_id)
        else:
            await manager.broadcast_to_all(notification)

    @staticmethod
    async def notify_typing(user_id: uuid.UUID, room_id: uuid.UUID, is_typing: bool = True):
        """Уведомление о наборе текста"""
        notification = {
            "type": "user_typing",
            "data": {
                "user_id": str(user_id),
                "room_id": str(room_id),
                "is_typing": is_typing
            }
        }

        await manager.broadcast_to_room(room_id, notification, exclude_user=user_id)

    @staticmethod
    async def notify_error(user_id: uuid.UUID, error_message: str, error_code: str):
        """Уведомление об ошибке"""
        notification = {
            "type": "error",
            "data": {
                "error_code": error_code,
                "error_message": error_message,
                "timestamp": datetime.utcnow().isoformat()
            }
        }

        await manager.send_to_user(user_id, notification)
