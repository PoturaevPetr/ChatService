"""
REST API endpoints для работы с черновиками сообщений (Cloud Drafts).
"""

from __future__ import annotations

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.database import get_db
from server.auth.middleware import get_current_user
from server.services.draft_service import draft_service

router = APIRouter(prefix="/api/v1/drafts", tags=["Drafts"])


class DraftPayload(BaseModel):
    encrypted_data: str = Field(..., description="AES-256-GCM encrypted draft text in base64")
    nonce: str = Field(..., description="Base64 nonce (12 bytes)")
    encrypted_aes_key: str = Field(..., description="RSA-OAEP encrypted AES key in base64")


class DraftResponse(BaseModel):
    room_id: str
    encrypted_data: str
    nonce: str
    encrypted_aes_key: str
    updated_at: str


@router.get("/", response_model=List[DraftResponse])
async def list_drafts(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Получить все зашифрованные черновики текущего пользователя."""
    uid = current_user["user_id"]
    drafts = await draft_service.get_user_drafts(uid, db)
    return drafts


@router.put("/{room_id}", response_model=DraftResponse)
async def save_draft(
    room_id: uuid.UUID,
    payload: DraftPayload,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Сохранить или обновить черновик для указанной комнаты."""
    uid = current_user["user_id"]
    saved = await draft_service.save_draft(
        user_id=uid,
        room_id=room_id,
        encrypted_data=payload.encrypted_data,
        nonce=payload.nonce,
        encrypted_aes_key=payload.encrypted_aes_key,
        db=db,
    )
    return saved


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    room_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Удалить черновик для указанной комнаты."""
    uid = current_user["user_id"]
    await draft_service.delete_draft(
        user_id=uid,
        room_id=room_id,
        db=db,
    )
    return None
