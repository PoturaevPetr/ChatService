from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status, Query, Header
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from server.database import get_db
from server.database.Messages import Messages
from server.database.RoomUsers import RoomUsers
from server.database.MessageRecipientKeys import MessageRecipientKeys
from server.database.MessageReads import MessageReads
from server.database.Rooms import Rooms
from server.auth.middleware import get_current_user
from server.services.message_service import message_service
from server.services.reaction_service import reaction_service
from server.services.room_services import room_service
from server.services.notification_service import NotificationService
from sqlalchemy.orm import Session
from sqlalchemy import func, exists


# Порог размера: в списке не отдаём тело сообщения, если больше (экономия трафика на медиа)
ATTACHMENT_SIZE_THRESHOLD = 2048


def _encrypted_fields_for_user(
    msg: Messages,
    user_id: uuid.UUID,
    db: Session,
    for_list: bool = False,
    device_id: Optional[str] = None,
):
    """
    Возвращает (encrypted_data, encrypted_aes_key, nonce, has_attachment, device_envelopes).
    Если for_list и тело сообщения больше порога — не отдаём тело (has_attachment=True), полное по GET /messages/:id.
    """
    enc_key, device_envelopes = message_service.resolve_decrypt_material_for_user(
        msg.id, user_id, db, device_id=device_id
    )
    if enc_key is None:
        return None
    if for_list and len(msg.encrypted_data or "") > ATTACHMENT_SIZE_THRESHOLD:
        return ("", enc_key or "", "", True, device_envelopes)
    return (msg.encrypted_data, enc_key or "", msg.nonce, False, device_envelopes)


router = APIRouter(prefix="/api/v1/messages", tags=["Messages"])


# Pydantic модели
class RecipientKeyPayload(BaseModel):
    user_id: uuid.UUID
    encrypted_aes_key: str


class DeviceEnvelopePayload(BaseModel):
    device_id: str
    type: str = "hybrid_rsa"
    body_b64: str
    user_id: Optional[uuid.UUID] = None


class E2EEncryptedPayload(BaseModel):
    encrypted_data: str
    nonce: str
    protocol: Optional[str] = "legacy_user_e2e"
    recipient_keys: Optional[List[RecipientKeyPayload]] = None
    envelopes: Optional[List[DeviceEnvelopePayload]] = None
    signature: Optional[str] = None


class SendMessageRequest(BaseModel):
    recipient_id: Optional[uuid.UUID] = Field(
        None,
        description="Для отправки без room_id — обязателен (второй участник 1-1). "
        "С room_id для direct можно не передавать (берётся второй участник комнаты). "
        "Для групповой комнаты не используется (одна строка messages, recipient_id NULL).",
    )
    e2e: E2EEncryptedPayload = Field(
        ...,
        description="Зашифрованный клиентом payload (E2E: сервер не видит plaintext)",
    )
    room_id: Optional[uuid.UUID] = Field(None, description="ID комнаты (для групповых чатов)")
    e2e_suppress_push: bool = Field(
        False,
        description="Не слать Novu/MIS (например call_log — пуши звонка отдельно).",
    )


class SendMessageResponse(BaseModel):
    message_id: uuid.UUID
    sender_id: uuid.UUID
    recipient_id: Optional[uuid.UUID]
    sent_at: datetime
    delivered: bool


class DeviceEnvelopeResponse(BaseModel):
    device_id: str
    encrypted_aes_key: str


class MessageResponse(BaseModel):
    message_id: uuid.UUID
    sender_id: uuid.UUID
    recipient_id: Optional[uuid.UUID]
    room_id: Optional[uuid.UUID]
    encrypted_data: str
    encrypted_aes_key: str
    nonce: str
    signature: Optional[str]
    is_read: bool
    sent_at: datetime
    has_attachment: bool = False  # True если в списке не отдали тело (большое); полное — по GET /messages/:id
    device_envelopes: Optional[List[DeviceEnvelopeResponse]] = None


class ReactionSetBody(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=32)


class ReactionSetResponse(BaseModel):
    removed: bool
    emoji: str


@router.post("/", response_model=SendMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Отправить E2E-зашифрованное сообщение.

    Клиент передаёт уже зашифрованный payload (`e2e`). Сервер не принимает plaintext.
    Доставка: WebSocket если получатель онлайн, иначе БД + push.
    """
    try:
        sender_id = current_user["user_id"]
        room_id = request.room_id
        if room_id is None:
            if request.recipient_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="recipient_id is required when room_id is omitted",
                )
            direct_room = await room_service.get_or_create_direct_room(db, sender_id, request.recipient_id)
            room_id = direct_room.id

        room = db.query(Rooms).filter(Rooms.id == room_id).first()
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

        member_rows = db.query(RoomUsers.user_id).filter(RoomUsers.room_id == room_id).all()
        member_ids = {r[0] for r in member_rows}
        if sender_id not in member_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not in this room",
            )

        is_direct_room = room.room_type == "direct"
        if is_direct_room:
            others = member_ids - {sender_id}
            if len(others) != 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid direct room membership",
                )
            recipient_db_id = next(iter(others))
            if request.recipient_id is not None and request.recipient_id != recipient_db_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="recipient_id does not match the other participant in this direct room",
                )
        else:
            recipient_db_id = None

        from server.services.e2e_payload import parse_e2e_for_send

        enc_data, nonce, signature, _protocol, recipient_keys, device_keys = parse_e2e_for_send(
            request.e2e, member_ids, db
        )

        message_data_for_meta: dict = {"_e2e": True}
        if request.e2e_suppress_push:
            message_data_for_meta["_suppress_novu"] = True

        message = await message_service.send_message(
            sender_id=sender_id,
            recipient_id=recipient_db_id,
            message_data=message_data_for_meta,
            encrypted_data=enc_data,
            nonce=nonce,
            signature=signature,
            room_id=room_id,
            db=db,
            recipient_keys=recipient_keys,
            device_keys=device_keys or None,
        )

        return SendMessageResponse(
            message_id=message.id,
            sender_id=message.sender_id,
            recipient_id=message.recipient_id,
            sent_at=message.sent_at,
            delivered=message.is_delivered
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {str(e)}"
        )


@router.get("/", response_model=List[MessageResponse])
async def get_messages(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    room_id: Optional[uuid.UUID] = Query(None, description="ID чата (комнаты) — только сообщения этого чата"),
    mark_read: bool = Query(False, description="Помечать входящие сообщения текущего пользователя в комнате как прочитанные"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить сообщения для текущего пользователя.

    Для polling клиентов без WebSocket.
    Если передан room_id — возвращаются только сообщения этого чата.
    X-Device-Id — выбрать wrap для hybrid_device_v0.
    """
    messages = message_service.get_messages(
        user_id=current_user["user_id"],
        db=db,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        room_id=room_id,
    )

    user_id = current_user["user_id"]
    device_id = (x_device_id or "").strip() or None

    # Если чат открыт — помечаем входящие сообщения как прочитанные.
    # Правило: читаем только входящие текущему пользователю (recipient=current_user),
    # сообщения отправленные самим пользователем (sender=current_user) не трогаем.
    if mark_read and room_id is not None:
        now = datetime.utcnow()
        rows_to_mark = (
            db.query(Messages.id, Messages.sender_id)
            .filter(
                Messages.room_id == room_id,
                Messages.recipient_id == user_id,
                Messages.sender_id != user_id,
                Messages.is_read == False,
            )
            .all()
        )
        if rows_to_mark:
            db.query(Messages).filter(
                Messages.room_id == room_id,
                Messages.recipient_id == user_id,
                Messages.sender_id != user_id,
                Messages.is_read == False,
            ).update(
                {Messages.is_read: True, Messages.status: "read", Messages.read_at: now},
                synchronize_session=False,
            )
            db.commit()

            for mid, sender_id in rows_to_mark:
                await NotificationService.notify_message_read(mid, user_id, sender_id)

        not_read = ~exists().where(
            MessageReads.message_id == Messages.id,
            MessageReads.user_id == user_id,
        )
        group_rows = (
            db.query(Messages.id, Messages.sender_id)
            .join(
                MessageRecipientKeys,
                (MessageRecipientKeys.message_id == Messages.id)
                & (MessageRecipientKeys.user_id == user_id),
            )
            .filter(
                Messages.room_id == room_id,
                Messages.recipient_id.is_(None),
                Messages.sender_id != user_id,
                not_read,
            )
            .all()
        )
        if group_rows:
            for mid, _sid in group_rows:
                db.add(
                    MessageReads(
                        message_id=mid,
                        user_id=user_id,
                        read_at=now,
                    )
                )
            db.commit()
            for mid, sender_id in group_rows:
                await NotificationService.notify_message_read(mid, user_id, sender_id)

        db.expire_all()

    result = []
    for msg in messages:
        fields = _encrypted_fields_for_user(msg, user_id, db, for_list=True, device_id=device_id)
        if fields is None:
            continue
        enc_data, enc_key, n, has_attachment, device_envelopes = fields
        result.append(
            MessageResponse(
                message_id=msg.id,
                sender_id=msg.sender_id,
                recipient_id=msg.recipient_id,
                room_id=msg.room_id,
                encrypted_data=enc_data,
                encrypted_aes_key=enc_key,
                nonce=n,
                signature=msg.signature,
                is_read=message_service.is_read_for_viewer(msg, user_id, db),
                sent_at=msg.sent_at,
                has_attachment=has_attachment,
                device_envelopes=[DeviceEnvelopeResponse(**e) for e in device_envelopes] or None,
            )
        )
    return result


@router.get("/unread", response_model=List[MessageResponse])
async def get_unread_messages(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить только непрочитанные сообщения"""
    return await get_messages(
        limit=100,
        offset=0,
        unread_only=True,
        current_user=current_user,
        db=db
    )


@router.get("/reactions/batch")
async def get_reactions_batch(
    room_id: uuid.UUID = Query(..., description="ID комнаты"),
    message_ids: str = Query(..., description="UUID сообщений через запятую, не более 100"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Реакции на сообщения в комнате (для отображения в ленте)."""
    parts = [p.strip() for p in message_ids.split(",") if p.strip()]
    if len(parts) > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many message_ids")
    mids: List[uuid.UUID] = []
    for p in parts:
        try:
            mids.append(uuid.UUID(p))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid message_id: {p}",
            )
    data = reaction_service.batch_for_messages(
        db,
        room_id=room_id,
        user_id=current_user["user_id"],
        message_ids=mids,
    )
    return {"reactions": data}


@router.post("/{message_id}/reactions", response_model=ReactionSetResponse)
async def set_message_reaction(
    message_id: uuid.UUID,
    body: ReactionSetBody,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Поставить / сменить реакцию (повтор того же эмодзи — снять)."""
    status, payload = reaction_service.set_reaction(
        db,
        user_id=current_user["user_id"],
        message_id=message_id,
        emoji=body.emoji.strip(),
    )
    if status == "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=payload.get("detail", "Bad request"),
        )
    await NotificationService.notify_message_reaction(
        room_id=payload["room_id"],
        message_id=payload["message_id"],
        user_id=payload["user_id"],
        emoji=payload["emoji"],
        removed=payload["removed"],
        notify_user_ids=payload["notify_user_ids"],
        message_sender_id=payload["message_sender_id"],
        db=db,
    )
    return ReactionSetResponse(removed=payload["removed"], emoji=payload["emoji"])


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: uuid.UUID,
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить конкретное сообщение"""
    message = message_service.get_message(
        message_id=message_id,
        user_id=current_user["user_id"],
        db=db
    )

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    device_id = (x_device_id or "").strip() or None
    fields = _encrypted_fields_for_user(
        message, current_user["user_id"], db, for_list=False, device_id=device_id
    )
    if fields is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot decrypt this message"
        )
    enc_data, enc_key, n, _, device_envelopes = fields
    return MessageResponse(
        message_id=message.id,
        sender_id=message.sender_id,
        recipient_id=message.recipient_id,
        room_id=message.room_id,
        encrypted_data=enc_data,
        encrypted_aes_key=enc_key,
        nonce=n,
        signature=message.signature,
        is_read=message_service.is_read_for_viewer(message, current_user["user_id"], db),
        sent_at=message.sent_at,
        has_attachment=False,
        device_envelopes=[DeviceEnvelopeResponse(**e) for e in device_envelopes] or None,
    )


@router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_message_as_read(
    message_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Пометить сообщение как прочитанное"""
    user_id = current_user["user_id"]
    preview = message_service.get_message(message_id, user_id, db)
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    if message_service.is_read_for_viewer(preview, user_id, db):
        return None

    sender_id = message_service.mark_as_read(
        message_id=message_id,
        user_id=user_id,
        db=db,
    )

    if sender_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    await NotificationService.notify_message_read(
        message_id, user_id, sender_id
    )
    return None


@router.post("/rooms/{room_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_room_messages_as_read(
    room_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Пометить как прочитанные все входящие сообщения в комнате для текущего пользователя.

    Правило:
    - личные входящие: recipient_id=current_user, обновляется messages.is_read;
    - группа (одна строка, recipient_id NULL): создаются записи message_reads для текущего пользователя.
    - исходящие сообщения текущего пользователя не трогаем.
    """
    user_id = current_user["user_id"]
    now = datetime.utcnow()

    rows_to_mark = (
        db.query(Messages.id, Messages.sender_id)
        .filter(
            Messages.room_id == room_id,
            Messages.recipient_id == user_id,
            Messages.sender_id != user_id,
            Messages.is_read == False,
        )
        .all()
    )
    if rows_to_mark:
        db.query(Messages).filter(
            Messages.room_id == room_id,
            Messages.recipient_id == user_id,
            Messages.sender_id != user_id,
            Messages.is_read == False,
        ).update(
            {
                Messages.is_read: True,
                Messages.status: "read",
                Messages.read_at: now,
            },
            synchronize_session=False,
        )
        db.commit()
        for mid, sender_id in rows_to_mark:
            await NotificationService.notify_message_read(mid, user_id, sender_id)

    not_read = ~exists().where(
        MessageReads.message_id == Messages.id,
        MessageReads.user_id == user_id,
    )
    group_rows = (
        db.query(Messages.id, Messages.sender_id)
        .join(
            MessageRecipientKeys,
            (MessageRecipientKeys.message_id == Messages.id)
            & (MessageRecipientKeys.user_id == user_id),
        )
        .filter(
            Messages.room_id == room_id,
            Messages.recipient_id.is_(None),
            Messages.sender_id != user_id,
            not_read,
        )
        .all()
    )
    if group_rows:
        for mid, _sid in group_rows:
            db.add(
                MessageReads(
                    message_id=mid,
                    user_id=user_id,
                    read_at=now,
                )
            )
        db.commit()
        for mid, sender_id in group_rows:
            await NotificationService.notify_message_read(mid, user_id, sender_id)
    return None


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удалить сообщение (только отправитель). У всех участников с ключом к сообщению оно пропадёт из UI по WebSocket."""
    result = message_service.delete_message_for_sender(
        message_id=message_id,
        user_id=current_user["user_id"],
        db=db,
    )
    if result == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )
    if result == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the sender can delete this message",
        )

    await NotificationService.notify_message_deleted(
        result["message_id"],
        result["room_id"],
        result["notify_user_ids"],
    )
    return None
