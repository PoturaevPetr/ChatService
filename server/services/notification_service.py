from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
import logging

from sqlalchemy.orm import Session

from server.websocket.manager import manager
from server.services import novu_service
from server.database.Users import Users
from server.settings import settings

logger = logging.getLogger(__name__)


def _novu_push_actor_name(user: Optional[Users]) -> str:
    """Подпись в Novu (поле senderName): как для пуша о новом сообщении — «Фамилия Имя»."""
    if not user:
        return "Участник"
    last = (user.last_name or "").strip()
    first = (user.first_name or "").strip()
    if last and first:
        return f"{last} {first}"
    if last:
        return last
    if first:
        return first
    return (user.username or "").strip() or "Участник"


class NotificationService:
    """Сервис уведомлений: онлайн-доставка нового сообщения и пуши (Novu)."""

    @staticmethod
    async def deliver_new_message_to_recipient(
        message_id: uuid.UUID,
        sender_id: uuid.UUID,
        recipient_id: uuid.UUID,
        room_id: Optional[uuid.UUID],
        encrypted_data: str,
        sent_at: datetime,
    ) -> None:
        """
        RabbitMQ → worker → Redis node channel.
        Fallback: локальный WebSocket manager.
        """
        from server.services.rabbit_delivery import publish_message_deliver

        queued = await publish_message_deliver(
            message_id=message_id,
            sender_id=sender_id,
            recipient_id=recipient_id,
            room_id=room_id,
            encrypted_data=encrypted_data,
            sent_at=sent_at,
        )

        if queued:
            logger.info("Message %s queued for delivery to %s", message_id, recipient_id)
            return

        notification = {
            "type": "new_message",
            "data": {
                "message_id": str(message_id),
                "sender_id": str(sender_id),
                "recipient_id": str(recipient_id) if recipient_id else None,
                "room_id": str(room_id) if room_id else None,
                "encrypted_data": encrypted_data,
                "sent_at": sent_at.isoformat(),
            },
        }

        if recipient_id:
            await manager.send_to_user(recipient_id, notification)
            logger.info("Notification sent to user %s for message %s", recipient_id, message_id)
        elif room_id:
            await manager.broadcast_to_room(room_id, notification, exclude_user=sender_id)
            logger.info("Notification broadcasted to room %s for message %s", room_id, message_id)

    @staticmethod
    async def push_new_message_via_novu(
        recipient_id: uuid.UUID,
        message_id: uuid.UUID,
        room_id: Optional[uuid.UUID],
        sender_display_name: str,
        type_message: str,
    ) -> None:
        """Пуш о новом сообщении через Novu (не mobileApp — у них отдельный колбэк в message_service)."""
        try:
            await novu_service.trigger_new_message_push(
                str(recipient_id),
                message_id=str(message_id),
                room_id=str(room_id) if room_id else None,
                sender_display_name=sender_display_name or "",
                type_message=type_message or "Новое сообщение",
            )
        except Exception:
            logger.exception("Novu push trigger failed for message %s", message_id)

    @staticmethod
    async def notify_message_reaction(
        room_id: uuid.UUID,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        emoji: str,
        removed: bool,
        notify_user_ids: List[uuid.UUID],
        message_sender_id: uuid.UUID,
        db: Session,
    ):
        """Всем участникам комнаты: обновление реакции на сообщение."""
        notification = {
            "type": "message_reaction",
            "data": {
                "room_id": str(room_id),
                "message_id": str(message_id),
                "user_id": str(user_id),
                "emoji": emoji,
                "removed": removed,
            },
        }
        seen = set()
        for uid in notify_user_ids:
            if uid in seen:
                continue
            seen.add(uid)
            await manager.send_to_user(uid, notification)
        logger.info(
            "message_reaction message_id=%s user_id=%s removed=%s -> %d users",
            message_id,
            user_id,
            removed,
            len(seen),
        )

        if not removed and message_sender_id != user_id:
            try:
                reactor = db.query(Users).filter(Users.id == user_id).first()
                reactor_name = _novu_push_actor_name(reactor)
                await novu_service.trigger_new_message_push(
                    str(message_sender_id),
                    message_id=str(message_id),
                    room_id=str(room_id),
                    sender_display_name=reactor_name,
                    type_message="Реакция на ваше сообщение",
                )
            except Exception:
                logger.exception(
                    "Novu push trigger failed for reaction message_id=%s recipient=%s",
                    message_id,
                    message_sender_id,
                )

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
    async def notify_message_deleted(
        message_id: uuid.UUID,
        room_id: Optional[uuid.UUID],
        notify_user_ids: List[uuid.UUID],
    ):
        """Уведомить всех, у кого был ключ к сообщению, что оно удалено (синхронизация клиентов)."""
        notification = {
            "type": "message_deleted",
            "data": {
                "message_id": str(message_id),
                "room_id": str(room_id) if room_id else None,
            },
        }
        seen = set()
        for uid in notify_user_ids:
            if uid in seen:
                continue
            seen.add(uid)
            await manager.send_to_user(uid, notification)
        logger.info(f"message_deleted sent to {len(seen)} users for message {message_id}")

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
