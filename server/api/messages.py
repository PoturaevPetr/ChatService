from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from server.database import get_db
from server.database.Messages import Messages
from server.database.UserKeys import UserKeys
from server.auth.middleware import get_current_user
from server.services.message_service import message_service
from sqlalchemy.orm import Session


router = APIRouter(prefix="/api/v1/messages", tags=["Messages"])


# Pydantic модели
class SendMessageRequest(BaseModel):
    recipient_id: uuid.UUID = Field(..., description="ID получателя")
    message: dict = Field(..., description="Исходное сообщение (будет зашифровано)")
    room_id: Optional[uuid.UUID] = Field(None, description="ID комнаты (для групповых чатов)")
    sign_message: bool = Field(False, description="Добавить цифровую подпись")


class SendMessageResponse(BaseModel):
    message_id: uuid.UUID
    sender_id: uuid.UUID
    recipient_id: uuid.UUID
    sent_at: datetime
    delivered: bool


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


@router.post("/", response_model=SendMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Отправить зашифрованное сообщение

    Сообщение будет зашифровано публичным ключом получателя и доставлено:
    - По WebSocket если получатель онлайн
    - Останется в БД для получения через REST если оффлайн

    - **recipient_id**: UUID получателя
    - **message**: Данные сообщения (любой JSON)
    - **room_id**: Опционально, для групповых чатов
    - **sign_message**: Добавить цифровую подпись
    """
    try:
        sender_id = current_user["user_id"]

        # Получаем публичный ключ получателя
        recipient_key = db.query(UserKeys).filter(
            UserKeys.user_id == request.recipient_id,
            UserKeys.is_active == True
        ).first()

        if not recipient_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recipient public key not found"
            )

        # Получаем приватный ключ отправителя (для подписи)
        sender_key = db.query(UserKeys).filter(
            UserKeys.user_id == sender_id,
            UserKeys.is_active == True
        ).first()

        # Шифруем сообщение
        encrypted = HybridEncryption.encrypt_message(
            message=request.message,
            recipient_public_key_pem=recipient_key.public_key.encode('utf-8')
        )

        # Добавляем цифровую подпись если нужно
        signature = None
        if request.sign_message and sender_key:
            message_str = str(request.message)
            signature = HybridEncryption.sign_message(
                message=message_str,
                private_key_pem=sender_key.private_key_encrypted.encode('utf-8')
            )

        # Отправляем сообщение (сохраняем в БД + уведомление по WebSocket)
        message = await message_service.send_message(
            sender_id=sender_id,
            recipient_id=request.recipient_id,
            message_data=request.message,
            encrypted_data=encrypted["encrypted_data"],
            encrypted_aes_key=encrypted["encrypted_aes_key"],
            nonce=encrypted["nonce"],
            signature=signature,
            room_id=request.room_id,
            db=db
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
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить сообщения для текущего пользователя

    Для polling клиентов без WebSocket
    """
    messages = message_service.get_messages(
        user_id=current_user["user_id"],
        db=db,
        limit=limit,
        offset=offset,
        unread_only=unread_only
    )

    return [
        MessageResponse(
            message_id=msg.id,
            sender_id=msg.sender_id,
            recipient_id=msg.recipient_id,
            room_id=msg.room_id,
            encrypted_data=msg.encrypted_data,
            encrypted_aes_key=msg.encrypted_aes_key,
            nonce=msg.nonce,
            signature=msg.signature,
            is_read=msg.is_read,
            sent_at=msg.sent_at
        )
        for msg in messages
    ]


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


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: uuid.UUID,
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

    return MessageResponse(
        message_id=message.id,
        sender_id=message.sender_id,
        recipient_id=message.recipient_id,
        room_id=message.room_id,
        encrypted_data=message.encrypted_data,
        encrypted_aes_key=message.encrypted_aes_key,
        nonce=message.nonce,
        signature=message.signature,
        is_read=message.is_read,
        sent_at=message.sent_at
    )


@router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_message_as_read(
    message_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Пометить сообщение как прочитанное"""
    success = message_service.mark_as_read(
        message_id=message_id,
        user_id=current_user["user_id"],
        db=db
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )

    return None
