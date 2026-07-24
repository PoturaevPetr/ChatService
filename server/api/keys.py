from typing import Dict, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import uuid

from server.database import get_db
from server.database.UserKeyBackups import UserKeyBackups
from server.auth.middleware import get_current_user
from sqlalchemy.orm import Session


router = APIRouter(prefix="/api/v1/keys", tags=["Keys Management"])


class KeyBackupBody(BaseModel):
    ciphertext: str = Field(..., min_length=16)
    kdf: str = Field("pbkdf2-sha256", max_length=64)
    kdf_salt_b64: str = Field(..., min_length=8)
    kdf_params: Dict[str, Any] = Field(default_factory=lambda: {"iterations": 310000})
    wrap_alg: str = Field("aes-256-gcm", max_length=64)
    nonce_b64: str = Field(..., min_length=8)


class KeyBackupResponse(BaseModel):
    ciphertext: str
    kdf: str
    kdf_salt_b64: str
    kdf_params: Dict[str, Any]
    wrap_alg: str
    nonce_b64: str
    updated_at: Optional[str] = None


@router.post("/me/public", status_code=status.HTTP_410_GONE)
async def upload_my_public_key_gone():
    """Removed — use POST /api/v1/devices/register."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="user_keys public upload removed; use /api/v1/devices/register",
    )


@router.put("/me/backup", response_model=KeyBackupResponse)
async def put_my_key_backup(
    body: KeyBackupBody,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Сохранить passphrase-encrypted private key blob (сервер не видит passphrase/private)."""
    uid = current_user["user_id"]
    now = datetime.now(timezone.utc)
    row = db.query(UserKeyBackups).filter(UserKeyBackups.user_id == uid).first()
    if row:
        row.ciphertext = body.ciphertext
        row.kdf = body.kdf
        row.kdf_salt_b64 = body.kdf_salt_b64
        row.kdf_params = body.kdf_params
        row.wrap_alg = body.wrap_alg
        row.nonce_b64 = body.nonce_b64
        row.updated_at = now
    else:
        row = UserKeyBackups(
            user_id=uid,
            ciphertext=body.ciphertext,
            kdf=body.kdf,
            kdf_salt_b64=body.kdf_salt_b64,
            kdf_params=body.kdf_params,
            wrap_alg=body.wrap_alg,
            nonce_b64=body.nonce_b64,
            created_at=now,
            updated_at=now,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return KeyBackupResponse(
        ciphertext=row.ciphertext,
        kdf=row.kdf,
        kdf_salt_b64=row.kdf_salt_b64,
        kdf_params=row.kdf_params or {},
        wrap_alg=row.wrap_alg,
        nonce_b64=row.nonce_b64,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/me/backup", response_model=KeyBackupResponse)
async def get_my_key_backup(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(UserKeyBackups)
        .filter(UserKeyBackups.user_id == current_user["user_id"])
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key backup not found")
    return KeyBackupResponse(
        ciphertext=row.ciphertext,
        kdf=row.kdf,
        kdf_salt_b64=row.kdf_salt_b64,
        kdf_params=row.kdf_params or {},
        wrap_alg=row.wrap_alg,
        nonce_b64=row.nonce_b64,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete("/me/backup", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_key_backup(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(UserKeyBackups)
        .filter(UserKeyBackups.user_id == current_user["user_id"])
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return None


@router.get("/public/{user_id}", status_code=status.HTTP_410_GONE)
async def get_public_key_gone(user_id: uuid.UUID):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="user_keys removed; use /api/v1/users/{id}/devices or /key-bundle",
    )


@router.get("/me/public", status_code=status.HTTP_410_GONE)
async def get_my_public_key_gone():
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="user_keys removed; use /api/v1/devices/me",
    )


@router.post("/me/rotate", status_code=status.HTTP_410_GONE)
async def rotate_my_keys_gone():
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="user_keys rotate removed; re-register device",
    )


@router.get("/service/{service_id}/users", status_code=status.HTTP_410_GONE)
async def get_service_users_keys_gone(service_id: str):
    raise HTTPException(status_code=status.HTTP_410_GONE, detail="Removed")
