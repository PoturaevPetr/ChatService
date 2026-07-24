"""V3.6: upload/list/download opaque encrypted history packs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth.middleware import get_current_user
from server.database import get_db
from server.database.EncryptedHistoryBlobs import EncryptedHistoryBlobs

router = APIRouter(prefix="/api/v1/history", tags=["Encrypted history"])

MAX_BLOB_CHARS = 2_000_000  # ~2MB base64 ceiling for v0


class HistoryUploadRequest(BaseModel):
    source_device_id: str = Field(..., min_length=8, max_length=64)
    ciphertext: str = Field(..., min_length=16)
    nonce_b64: str = Field(..., min_length=8)
    meta_json: Optional[str] = None
    ttl_hours: int = Field(72, ge=1, le=24 * 14)


class HistoryBlobInfo(BaseModel):
    id: uuid.UUID
    source_device_id: str
    byte_size: int
    created_at: str
    expires_at: Optional[str] = None
    meta_json: Optional[str] = None


class HistoryBlobDownload(HistoryBlobInfo):
    ciphertext: str
    nonce_b64: str


@router.post("/blobs", response_model=HistoryBlobInfo, status_code=status.HTTP_201_CREATED)
async def upload_history_blob(
    body: HistoryUploadRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(body.ciphertext) > MAX_BLOB_CHARS:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Blob too large")
    now = datetime.now(timezone.utc)
    row = EncryptedHistoryBlobs(
        user_id=current_user["user_id"],
        source_device_id=body.source_device_id.strip(),
        ciphertext=body.ciphertext,
        nonce_b64=body.nonce_b64,
        meta_json=body.meta_json,
        byte_size=len(body.ciphertext),
        created_at=now,
        expires_at=now + timedelta(hours=body.ttl_hours),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return HistoryBlobInfo(
        id=row.id,
        source_device_id=row.source_device_id,
        byte_size=row.byte_size,
        created_at=row.created_at.isoformat(),
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        meta_json=row.meta_json,
    )


@router.get("/blobs", response_model=List[HistoryBlobInfo])
async def list_history_blobs(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rows = (
        db.query(EncryptedHistoryBlobs)
        .filter(EncryptedHistoryBlobs.user_id == current_user["user_id"])
        .order_by(EncryptedHistoryBlobs.created_at.desc())
        .limit(20)
        .all()
    )
    out = []
    for row in rows:
        if row.expires_at and row.expires_at < now:
            continue
        out.append(
            HistoryBlobInfo(
                id=row.id,
                source_device_id=row.source_device_id,
                byte_size=row.byte_size,
                created_at=row.created_at.isoformat() if row.created_at else now.isoformat(),
                expires_at=row.expires_at.isoformat() if row.expires_at else None,
                meta_json=row.meta_json,
            )
        )
    return out


@router.get("/blobs/{blob_id}", response_model=HistoryBlobDownload)
async def download_history_blob(
    blob_id: uuid.UUID,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(EncryptedHistoryBlobs)
        .filter(
            EncryptedHistoryBlobs.id == blob_id,
            EncryptedHistoryBlobs.user_id == current_user["user_id"],
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blob not found")
    now = datetime.now(timezone.utc)
    if row.expires_at and row.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Blob expired")
    return HistoryBlobDownload(
        id=row.id,
        source_device_id=row.source_device_id,
        byte_size=row.byte_size,
        created_at=row.created_at.isoformat() if row.created_at else now.isoformat(),
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        meta_json=row.meta_json,
        ciphertext=row.ciphertext,
        nonce_b64=row.nonce_b64,
    )


@router.delete("/blobs/{blob_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history_blob(
    blob_id: uuid.UUID,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(EncryptedHistoryBlobs)
        .filter(
            EncryptedHistoryBlobs.id == blob_id,
            EncryptedHistoryBlobs.user_id == current_user["user_id"],
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return None
