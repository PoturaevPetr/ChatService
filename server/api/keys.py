from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel
from datetime import datetime
import uuid

from server.database import get_db
from server.database.Users import Users
from server.database.UserKeys import UserKeys
from server.auth.middleware import get_current_user
from server.crypto.key_manager import KeyManager
from sqlalchemy.orm import Session


router = APIRouter(prefix="/api/v1/keys", tags=["Keys Management"])


# Pydantic модели
class PublicKeyResponse(BaseModel):
    user_id: uuid.UUID
    public_key: str
    key_type: str
    key_fingerprint: str
    created_at: str


class KeyRotationResponse(BaseModel):
    public_key: str
    private_key: str  # Только при ротации
    key_fingerprint: str
    rotated_at: str


@router.get("/public/{user_id}", response_model=PublicKeyResponse)
async def get_public_key(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    """
    Получить публичный ключ пользователя по user_id

    Необходима аутентификация
    """
    # Проверяем существование пользователя
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Получаем активный ключ
    user_key = db.query(UserKeys).filter(
        UserKeys.user_id == user_id,
        UserKeys.is_active == True
    ).first()

    if not user_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active key not found for user"
        )

    return PublicKeyResponse(
        user_id=user.id,
        public_key=user_key.public_key,
        key_type=user_key.key_type,
        key_fingerprint=user_key.key_fingerprint,
        created_at=user_key.created_at.isoformat()
    )


@router.get("/me/public", response_model=PublicKeyResponse)
async def get_my_public_key(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить свой публичный ключ"""
    return await get_public_key(current_user["user_id"], db, current_user)


@router.post("/me/rotate", response_model=KeyRotationResponse)
async def rotate_my_keys(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ротация своей ключевой пары

    Генерирует новую пару ключей и деактивирует старую
    """
    # Получаем текущий ключ
    old_key = db.query(UserKeys).filter(
        UserKeys.user_id == current_user["user_id"],
        UserKeys.is_active == True
    ).first()

    if not old_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active key found"
        )

    # Генерируем новую пару
    new_keypair = KeyManager.rotate_key(old_key.private_key_encrypted)

    # Деактивируем старый ключ
    old_key.is_active = False
    old_key.rotated_at = datetime.utcnow()

    # Создаем новую запись
    new_key = UserKeys(
        user_id=current_user["user_id"],
        public_key=new_keypair["public_key"],
        private_key_encrypted=new_keypair["private_key"],
        key_type="RSA-4096",
        key_fingerprint=KeyManager.export_public_key(new_keypair["public_key"], format="fingerprint"),
        is_active=True
    )
    db.add(new_key)
    db.commit()

    return KeyRotationResponse(
        public_key=new_keypair["public_key"],
        private_key=new_keypair["private_key"],  # Возвращаем только при ротации!
        key_fingerprint=new_key.key_fingerprint,
        rotated_at=new_keypair["rotated_at"]
    )


@router.get("/service/{service_id}/users", response_model=list[PublicKeyResponse])
async def get_service_users_keys(
    service_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить публичные ключи всех пользователей сервиса

    Полезно для массовой рассылки
    """
    # Проверяем права доступа
    if current_user.get("token_type") != "api_key":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only service accounts can access this endpoint"
        )

    # Получаем всех пользователей сервиса
    users = db.query(Users).filter(Users.service_id == service_id).all()

    result = []
    for user in users:
        user_key = db.query(UserKeys).filter(
            UserKeys.user_id == user.id,
            UserKeys.is_active == True
        ).first()

        if user_key:
            result.append(PublicKeyResponse(
                user_id=user.id,
                public_key=user_key.public_key,
                key_type=user_key.key_type,
                key_fingerprint=user_key.key_fingerprint,
                created_at=user_key.created_at.isoformat()
            ))

    return result
