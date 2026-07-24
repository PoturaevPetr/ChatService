from typing import Dict, Any, Optional, List, Tuple, Union, Literal
from datetime import datetime
import uuid
import logging
import asyncio

from server.database.Messages import Messages
from server.database.MessageRecipientKeys import MessageRecipientKeys
from server.database.MessageReads import MessageReads
from server.database.Users import Users
from server.services.notification_service import NotificationService
from server.services.callback_service import CallbackService
from server.settings import settings
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, exists

logger = logging.getLogger(__name__)


def _user_display_name(user: Optional[Users]) -> str:
    if not user:
        return ""
    parts = [user.first_name, user.last_name, user.middle_name]
    name = " ".join(p.strip() for p in parts if p and str(p).strip())
    return name or (user.username or "")


def _user_push_sender_name(user: Optional[Users]) -> str:
    """Для пуша Novu: только фамилия и имя (без отчества), порядок «Фамилия Имя»."""
    if not user:
        return ""
    last = (user.last_name or "").strip()
    first = (user.first_name or "").strip()
    if last and first:
        return f"{last} {first}"
    if last:
        return last
    if first:
        return first
    return (user.username or "").strip() or "Контакт"


def _mime_to_push_type_label(mime: str) -> str:
    m = (mime or "").strip().lower()
    if not m:
        return "Новое вложение"
    if m.startswith("audio/"):
        return "Новое голосовое сообщение"
    if m.startswith("image/"):
        return "Новое фото"
    if m.startswith("video/"):
        return "Новое видеосообщение"
    if m == "application/pdf" or m.endswith("/pdf"):
        return "Новый документ"
    if m.startswith("text/"):
        return "Новый текстовый файл"
    if m.startswith("application/"):
        return "Новый файл"
    return "Новое вложение"


def _e2e_suppress_novu_push(message_data: Optional[Dict[str, Any]]) -> bool:
    """E2E: не слать Novu/MIS (например журнал звонка — пуш уже от MeetService)."""
    return bool(isinstance(message_data, dict) and message_data.get("_suppress_novu") is True)


def _push_type_message_label(message_data: Optional[Dict[str, Any]]) -> str:
    """
    Человекочитаемый текст для Novu payload.typeMessage (без расшифровки тела).
    Клиент: { text }, { file }, { file_ref } (+ mimeType).
    """
    if not message_data or not isinstance(message_data, dict):
        return "Новое сообщение"
    ref = message_data.get("file_ref")
    if isinstance(ref, dict):
        return _mime_to_push_type_label(str(ref.get("mimeType") or ""))
    f = message_data.get("file")
    if isinstance(f, dict):
        return _mime_to_push_type_label(str(f.get("mimeType") or ""))
    return "Новое сообщение"


class MessageService:
    """Сервис для обработки сообщений с кросс-доставкой"""

    @staticmethod
    def is_read_for_viewer(message: Messages, viewer_id: uuid.UUID, db: Session) -> bool:
        """Прочитано ли сообщение с точки зрения viewer_id (direct: колонка messages; группа A: message_reads)."""
        if message.recipient_id == viewer_id:
            return bool(message.is_read)
        if message.recipient_id is None:
            if message.sender_id == viewer_id:
                return bool(message.is_read)
            return (
                db.query(MessageReads)
                .filter(MessageReads.message_id == message.id, MessageReads.user_id == viewer_id)
                .first()
                is not None
            )
        return bool(message.is_read)

    @staticmethod
    def message_ids_read_by_user(db: Session, message_ids: List[uuid.UUID], user_id: uuid.UUID) -> set[uuid.UUID]:
        if not message_ids:
            return set()
        rows = (
            db.query(MessageReads.message_id)
            .filter(MessageReads.user_id == user_id, MessageReads.message_id.in_(message_ids))
            .all()
        )
        return {r[0] for r in rows}

    @staticmethod
    async def send_message(
        sender_id: uuid.UUID,
        recipient_id: Optional[uuid.UUID],
        message_data: Dict[str, Any],
        encrypted_data: str,
        nonce: str,
        signature: Optional[str],
        room_id: Optional[uuid.UUID],
        db: Session,
        recipient_keys: List[Tuple[uuid.UUID, str]],
        device_keys: Optional[List[Tuple[uuid.UUID, str, str]]] = None,
    ) -> Messages:
        """
        Одно тело сообщения в БД; ключи — message_recipient_keys (user) и
        опционально message_device_keys (hybrid_device_v0).
        recipient_keys: [(user_id, encrypted_aes_key_b64), ...]
        device_keys: [(user_id, device_id, encrypted_aes_key_b64), ...]
        """
        from server.database.MessageDeviceKeys import MessageDeviceKeys

        recipient: Optional[Users] = None
        if recipient_id is not None:
            recipient = db.query(Users).filter(Users.id == recipient_id).first()
            if not recipient:
                raise ValueError(f"Recipient {recipient_id} not found")
        elif room_id is None:
            raise ValueError("recipient_id is required when room_id is missing")

        first_key = recipient_keys[0][1] if recipient_keys else None
        message = Messages(
            sender_id=sender_id,
            recipient_id=recipient_id,
            room_id=room_id,
            encrypted_data=encrypted_data,
            nonce=nonce,
            encrypted_aes_key=first_key,
            signature=signature,
            message_type="direct" if not room_id else "group",
            status="sent",
            is_read=False,
            is_delivered=False,
            sent_at=datetime.utcnow()
        )

        db.add(message)
        db.flush()

        for user_id, encrypted_aes_key in recipient_keys:
            db.add(
                MessageRecipientKeys(
                    message_id=message.id,
                    user_id=user_id,
                    encrypted_aes_key=encrypted_aes_key,
                )
            )
        for user_id, device_id, encrypted_aes_key in (device_keys or []):
            db.add(
                MessageDeviceKeys(
                    message_id=message.id,
                    user_id=user_id,
                    device_id=device_id,
                    encrypted_aes_key=encrypted_aes_key,
                )
            )
        db.flush()

        db.commit()
        db.refresh(message)

        count = db.query(MessageRecipientKeys).filter(MessageRecipientKeys.message_id == message.id).count()
        dcount = (
            db.query(MessageDeviceKeys).filter(MessageDeviceKeys.message_id == message.id).count()
            if device_keys
            else 0
        )
        logger.info(
            f"Message {message.id} saved from {sender_id} to recipient_id={recipient_id}, "
            f"recipient_keys={len(recipient_keys)}, device_keys={dcount}"
        )
        if count == 0 and recipient_keys:
            logger.warning("message_recipient_keys is empty after commit despite recipient_keys being non-empty")
        sender_row = db.query(Users).filter(Users.id == sender_id).first()
        sender_push = _user_push_sender_name(sender_row)

        type_label = _push_type_message_label(message_data)
        notify_user_ids = [uid for uid, _ in recipient_keys if uid != sender_id]
        skip_push = _e2e_suppress_novu_push(message_data)

        async def _mobile_mis_then_novu_fallback(
            nid: uuid.UUID,
            mis_url: str,
        ) -> None:
            """
            MIS для mobileApp не блокирует send_message (message_sent у отправителя).
            При сбое MIS — Novu (если настроен), иначе мобильный клиент остаётся без пуша.
            """
            try:
                await CallbackService.callback_new_message_mis(
                    url=mis_url,
                    message_id=message.id,
                    sender_id=sender_id,
                    recipient_id=nid,
                    room_id=room_id,
                    encrypted_data=encrypted_data,
                    sent_at=message.sent_at,
                )
            except Exception:
                logger.exception(
                    "mobileApp MIS callback failed for message %s recipient %s; trying Novu fallback",
                    message.id,
                    nid,
                )
                try:
                    await NotificationService.push_new_message_via_novu(
                        recipient_id=nid,
                        message_id=message.id,
                        room_id=room_id,
                        sender_display_name=sender_push,
                        type_message=type_label,
                    )
                except Exception:
                    logger.exception(
                        "Novu fallback after MIS failure failed for message %s recipient %s",
                        message.id,
                        nid,
                    )

        for nid in notify_user_ids:
            user_row = db.query(Users).filter(Users.id == nid).first()
            await NotificationService.deliver_new_message_to_recipient(
                message_id=message.id,
                sender_id=sender_id,
                recipient_id=nid,
                room_id=room_id,
                encrypted_data=encrypted_data,
                sent_at=message.sent_at,
            )
            if skip_push:
                continue
            if room_id and not MessageService.user_notifications_enabled_for_room(nid, room_id, db):
                continue
            use_mobile_callback = (
                user_row
                and user_row.service_id == "mobileApp"
                and bool(settings.MOBILE_APP_PUSH_CALLBACK_URL)
            )
            if use_mobile_callback:
                # Не await: иначе send_message (и WS message_sent) ждут все HTTP к MIS по каждому участнику.
                asyncio.create_task(
                    _mobile_mis_then_novu_fallback(nid, settings.MOBILE_APP_PUSH_CALLBACK_URL)
                )
            else:
                await NotificationService.push_new_message_via_novu(
                    recipient_id=nid,
                    message_id=message.id,
                    room_id=room_id,
                    sender_display_name=sender_push,
                    type_message=type_label,
                )

        return message

    @staticmethod
    def get_message_key_for_device(
        message_id: uuid.UUID, user_id: uuid.UUID, device_id: str, db: Session
    ) -> Optional[str]:
        """Ключ для конкретного device (hybrid_device_v0)."""
        from server.database.MessageDeviceKeys import MessageDeviceKeys

        row = (
            db.query(MessageDeviceKeys)
            .filter(
                MessageDeviceKeys.message_id == message_id,
                MessageDeviceKeys.user_id == user_id,
                MessageDeviceKeys.device_id == device_id,
            )
            .first()
        )
        return row.encrypted_aes_key if row else None

    @staticmethod
    def user_notifications_enabled_for_room(
        user_id: uuid.UUID, room_id: uuid.UUID, db: Session
    ) -> bool:
        from server.database.RoomUsers import RoomUsers

        row = (
            db.query(RoomUsers.notifications_enabled)
            .filter(RoomUsers.user_id == user_id, RoomUsers.room_id == room_id)
            .first()
        )
        if not row:
            return True
        enabled = row[0]
        return True if enabled is None else bool(enabled)

    @staticmethod
    def resolve_decrypt_material_for_user(
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        db: Session,
        device_id: Optional[str] = None,
    ) -> Tuple[Optional[str], List[Dict[str, str]]]:
        """
        Signal/hybrid envelope body + per-device wraps for this user.
        Returns (None, []) when the user has no decrypt material.
        """
        device_envelopes = MessageService.get_message_device_keys_for_user(message_id, user_id, db)
        enc_key = MessageService.get_message_key_for_user(message_id, user_id, db, device_id=device_id)
        if enc_key is None and device_envelopes:
            if device_id:
                match = next((e for e in device_envelopes if e.get("device_id") == device_id), None)
                if match:
                    enc_key = match.get("encrypted_aes_key") or ""
            if not enc_key:
                enc_key = device_envelopes[0].get("encrypted_aes_key") or ""
        if enc_key is None:
            enc_key = MessageService.get_message_key_for_user(message_id, user_id, db, device_id=None) or ""
        if not enc_key and not device_envelopes:
            return None, []
        return enc_key or "", device_envelopes

    @staticmethod
    def get_message_device_keys_for_user(
        message_id: uuid.UUID, user_id: uuid.UUID, db: Session
    ) -> List[Dict[str, str]]:
        from server.database.MessageDeviceKeys import MessageDeviceKeys

        rows = (
            db.query(MessageDeviceKeys)
            .filter(MessageDeviceKeys.message_id == message_id, MessageDeviceKeys.user_id == user_id)
            .all()
        )
        return [{"device_id": r.device_id, "encrypted_aes_key": r.encrypted_aes_key} for r in rows]

    @staticmethod
    def get_message_key_for_user(
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        db: Session,
        device_id: Optional[str] = None,
    ) -> Optional[str]:
        """Ключ расшифровки: device wrap (если device_id) → recipient_keys → legacy."""
        if device_id:
            dk = MessageService.get_message_key_for_device(message_id, user_id, device_id, db)
            if dk:
                return dk
            # Fall through to message_recipient_keys (signal_v1 user wrap) even if other device rows exist.
        row = db.query(MessageRecipientKeys).filter(
            MessageRecipientKeys.message_id == message_id,
            MessageRecipientKeys.user_id == user_id,
        ).first()
        if row:
            return row.encrypted_aes_key
        msg = db.query(Messages).filter(Messages.id == message_id).first()
        if msg and msg.recipient_id == user_id and msg.encrypted_aes_key:
            return msg.encrypted_aes_key
        return None

    @staticmethod
    def get_messages(
        user_id: uuid.UUID,
        db: Session,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
        room_id: Optional[uuid.UUID] = None,
    ) -> list[Messages]:
        """
        Получение сообщений для пользователя.

        Args:
            user_id: ID пользователя
            db: Сессия БД
            limit: Лимит сообщений
            offset: Сдвиг
            unread_only: Только непрочитанные
            room_id: Опционально — только сообщения этого чата (комнаты)

        Returns:
            Список сообщений
        """
        # Сообщения, которые пользователь может прочитать: есть ключ в message_recipient_keys или legacy
        sub = db.query(MessageRecipientKeys.message_id).filter(MessageRecipientKeys.user_id == user_id)
        query = db.query(Messages).filter(
            or_(
                Messages.id.in_(sub),
                (Messages.recipient_id == user_id) & (Messages.encrypted_aes_key.isnot(None)),
            )
        )

        if room_id is not None:
            query = query.filter(Messages.room_id == room_id)

        if unread_only:
            read_exists = exists().where(
                MessageReads.message_id == Messages.id,
                MessageReads.user_id == user_id,
            )
            query = query.filter(
                or_(
                    and_(Messages.recipient_id == user_id, Messages.is_read == False),
                    and_(
                        Messages.recipient_id.is_(None),
                        Messages.sender_id != user_id,
                        ~read_exists,
                    ),
                )
            )

        messages = query.order_by(Messages.sent_at.desc()).limit(limit).offset(offset).all()

        return messages

    @staticmethod
    def mark_as_delivered(message_id: uuid.UUID, db: Session) -> bool:
        """Пометить сообщение как доставленное (вызывает воркер после отправки по WebSocket)."""
        message = db.query(Messages).filter(Messages.id == message_id).first()
        if not message:
            return False
        message.status = "delivered"
        message.is_delivered = True
        message.delivered_at = datetime.utcnow()
        db.commit()
        return True

    @staticmethod
    def mark_as_read(message_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> Optional[uuid.UUID]:
        """
        Пометить сообщение как прочитанное.
        Возвращает sender_id для уведомления отправителя, либо None если сообщение не найдено
        или пользователь не может пометить прочтение.
        """
        message = db.query(Messages).filter(Messages.id == message_id).first()
        if not message:
            return None

        if message.sender_id == user_id:
            return None

        if message.recipient_id == user_id:
            if message.is_read:
                return None
            sender_id = message.sender_id
            message.is_read = True
            message.status = "read"
            message.read_at = datetime.utcnow()
            db.commit()
            return sender_id

        if message.recipient_id is not None:
            return None

        if not MessageService.get_message_key_for_user(message_id, user_id, db):
            return None

        if (
            db.query(MessageReads)
            .filter(MessageReads.message_id == message_id, MessageReads.user_id == user_id)
            .first()
        ):
            return None

        db.add(
            MessageReads(
                message_id=message_id,
                user_id=user_id,
                read_at=datetime.utcnow(),
            )
        )
        db.commit()
        return message.sender_id

    @staticmethod
    def get_message(message_id: uuid.UUID, user_id: uuid.UUID, db: Session) -> Optional[Messages]:
        """Получить сообщение, если пользователь может его прочитать (отправитель, получатель или есть ключ)."""
        msg = db.query(Messages).filter(Messages.id == message_id).first()
        if not msg:
            return None
        if msg.sender_id == user_id or msg.recipient_id == user_id:
            return msg
        if db.query(MessageRecipientKeys).filter(
            MessageRecipientKeys.message_id == message_id,
            MessageRecipientKeys.user_id == user_id,
        ).first():
            return msg
        return None

    @staticmethod
    def delete_message_for_sender(
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        db: Session,
    ) -> Union[Literal["not_found"], Literal["forbidden"], Dict[str, Any]]:
        """
        Удалить сообщение из БД (только отправитель).
        Возвращает данные для WS-уведомления участникам с ключом в message_recipient_keys
        (или sender/recipient для legacy без строк ключей).
        """
        msg = db.query(Messages).filter(Messages.id == message_id).first()
        if not msg:
            return "not_found"
        if msg.sender_id != user_id:
            return "forbidden"

        uid_rows = (
            db.query(MessageRecipientKeys.user_id)
            .filter(MessageRecipientKeys.message_id == message_id)
            .distinct()
            .all()
        )
        notify_ids: List[uuid.UUID] = list({r[0] for r in uid_rows})
        if not notify_ids:
            notify_ids = [msg.sender_id]
            if msg.recipient_id:
                notify_ids.append(msg.recipient_id)
            notify_ids = list({u for u in notify_ids if u is not None})

        room_id = msg.room_id
        mid = msg.id

        db.query(MessageRecipientKeys).filter(MessageRecipientKeys.message_id == message_id).delete(
            synchronize_session=False
        )
        db.delete(msg)
        db.commit()

        return {
            "message_id": mid,
            "room_id": room_id,
            "notify_user_ids": notify_ids,
        }


# Глобальный экземпляр
message_service = MessageService()
