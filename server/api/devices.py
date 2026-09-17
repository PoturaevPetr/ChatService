"""CRYPTO_DEVICES_V3: регистрация устройств и key bundles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth.middleware import get_current_user
from server.database import get_db
from server.database.Devices import Devices, DeviceOneTimePrekeys
from server.database.Users import Users
from server.services.device_service import DeviceRegisterPayload, upsert_user_device

router = APIRouter(prefix="/api/v1", tags=["Devices"])


class OneTimePrekeyIn(BaseModel):
    key_id: int = Field(..., ge=1)
    public_key: str = Field(..., min_length=16)


class DeviceRegisterRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=64)
    name: Optional[str] = Field(None, max_length=255)
    platform: str = Field("web", max_length=32)
    identity_key_public: str = Field(..., min_length=16)
    signal_identity_key_public: Optional[str] = Field(
        None, description="Curve25519 identity public (base64) for signal_v1"
    )
    registration_id: int = Field(0, ge=0)
    signed_prekey_id: Optional[int] = None
    signed_prekey_public: Optional[str] = None
    signed_prekey_signature: Optional[str] = None
    one_time_prekeys: List[OneTimePrekeyIn] = Field(default_factory=list)


class DeviceResponse(BaseModel):
    id: uuid.UUID
    device_id: str
    name: Optional[str]
    platform: str
    identity_key_public: str
    signal_identity_key_public: Optional[str] = None
    registration_id: int
    signed_prekey_id: Optional[int] = None
    signed_prekey_public: Optional[str] = None
    is_active: bool
    last_seen_at: Optional[str] = None
    created_at: Optional[str] = None
    unused_otpk_count: int = 0
    linked_at: Optional[str] = None


class DeviceBundleItem(BaseModel):
    device_id: str
    identity_key_public: str
    signal_identity_key_public: Optional[str] = None
    registration_id: int
    signed_prekey_id: Optional[int] = None
    signed_prekey_public: Optional[str] = None
    signed_prekey_signature: Optional[str] = None
    one_time_prekey: Optional[OneTimePrekeyIn] = None


class UserKeyBundleResponse(BaseModel):
    user_id: uuid.UUID
    devices: List[DeviceBundleItem]


class PrekeysReplenishRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=64)
    one_time_prekeys: List[OneTimePrekeyIn] = Field(..., min_length=1)


class LinkStartRequest(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=64)


class LinkStartResponse(BaseModel):
    link_id: uuid.UUID
    code: str
    expires_at: str
    qr_payload: str


class LinkFinishRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)
    device_id: str = Field(..., min_length=8, max_length=64)


class LinkFinishResponse(BaseModel):
    device_id: str
    linked: bool


class ApproveLoginRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=16)
    device_id: str = Field(..., min_length=8, max_length=64)
    encrypted_master_key: Optional[str] = None


class ApproveLoginResponse(BaseModel):
    approved: bool
    login_device_id: str


def _unused_otpk_count(db: Session, device_row_id: uuid.UUID) -> int:
    return (
        db.query(DeviceOneTimePrekeys)
        .filter(
            DeviceOneTimePrekeys.device_row_id == device_row_id,
            DeviceOneTimePrekeys.consumed_at.is_(None),
        )
        .count()
    )


def _device_to_response(row: Devices, db: Optional[Session] = None) -> DeviceResponse:
    unused = _unused_otpk_count(db, row.id) if db is not None else 0
    linked = getattr(row, "linked_at", None)
    return DeviceResponse(
        id=row.id,
        device_id=row.device_id,
        name=row.name,
        platform=row.platform,
        identity_key_public=row.identity_key_public,
        signal_identity_key_public=getattr(row, "signal_identity_key_public", None),
        registration_id=row.registration_id,
        signed_prekey_id=row.signed_prekey_id,
        signed_prekey_public=row.signed_prekey_public,
        is_active=row.is_active,
        last_seen_at=row.last_seen_at.isoformat() if row.last_seen_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
        unused_otpk_count=unused,
        linked_at=linked.isoformat() if linked else None,
    )


@router.post("/devices/register", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    body: DeviceRegisterRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Зарегистрировать или обновить устройство текущего пользователя."""
    uid = current_user["user_id"]
    payload = DeviceRegisterPayload(
        device_id=body.device_id,
        name=body.name,
        platform=body.platform,
        identity_key_public=body.identity_key_public,
        signal_identity_key_public=body.signal_identity_key_public,
        registration_id=body.registration_id,
        signed_prekey_id=body.signed_prekey_id,
        signed_prekey_public=body.signed_prekey_public,
        signed_prekey_signature=body.signed_prekey_signature,
        one_time_prekeys=body.one_time_prekeys,
    )
    row = upsert_user_device(db, uid, payload)
    db.commit()
    db.refresh(row)
    return _device_to_response(row, db)


@router.get("/devices/me", response_model=List[DeviceResponse])
async def list_my_devices(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Devices)
        .filter(Devices.user_id == current_user["user_id"], Devices.is_active == True)
        .order_by(Devices.created_at.asc())
        .all()
    )
    return [_device_to_response(r, db) for r in rows]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: str,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(Devices)
        .filter(
            Devices.user_id == current_user["user_id"],
            Devices.device_id == device_id,
            Devices.is_active == True,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    row.is_active = False
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return None


class StaleDeviceCleanupRequest(BaseModel):
    stale_days: int = Field(90, ge=1, le=365, description="Деактивировать устройства, не выходившие на связь N дней")


@router.post("/devices/me/cleanup-stale")
async def cleanup_stale_devices(
    body: StaleDeviceCleanupRequest = StaleDeviceCleanupRequest(),
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Деактивировать устройства текущего пользователя, которые не были онлайн
    более stale_days дней. Помогает избежать ошибок при отправке E2E-сообщений
    когда есть «мёртвые» устройства.
    """
    from datetime import timedelta

    user_id = current_user["user_id"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=body.stale_days)
    stale_rows = (
        db.query(Devices)
        .filter(
            Devices.user_id == user_id,
            Devices.is_active == True,
            Devices.revoked_at.is_(None),
            Devices.last_seen_at < cutoff,
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    deactivated = []
    for row in stale_rows:
        row.is_active = False
        row.revoked_at = now
        deactivated.append(row.device_id)
    db.commit()
    return {
        "deactivated_count": len(deactivated),
        "deactivated_device_ids": deactivated,
        "stale_days": body.stale_days,
    }


@router.put("/devices/me/prekeys", status_code=status.HTTP_204_NO_CONTENT)
async def replenish_prekeys(
    body: PrekeysReplenishRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(Devices)
        .filter(
            Devices.user_id == current_user["user_id"],
            Devices.device_id == body.device_id,
            Devices.is_active == True,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    for otpk in body.one_time_prekeys:
        exists = (
            db.query(DeviceOneTimePrekeys)
            .filter(
                DeviceOneTimePrekeys.device_row_id == row.id,
                DeviceOneTimePrekeys.key_id == otpk.key_id,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            DeviceOneTimePrekeys(
                device_row_id=row.id,
                key_id=otpk.key_id,
                public_key=otpk.public_key,
            )
        )
    row.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return None


@router.get("/users/{user_id}/devices", response_model=UserKeyBundleResponse)
async def list_user_devices(
    user_id: uuid.UUID,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Активные устройства пользователя (identity keys only).
    Без consume one-time prekeys — для hybrid_device_v0 fan-out.
    """
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    devices = (
        db.query(Devices)
        .filter(Devices.user_id == user_id, Devices.is_active == True, Devices.revoked_at.is_(None))
        .all()
    )
    items = [
        DeviceBundleItem(
            device_id=d.device_id,
            identity_key_public=d.identity_key_public,
            signal_identity_key_public=getattr(d, "signal_identity_key_public", None),
            registration_id=d.registration_id,
            signed_prekey_id=d.signed_prekey_id,
            signed_prekey_public=d.signed_prekey_public,
            signed_prekey_signature=d.signed_prekey_signature,
            one_time_prekey=None,
        )
        for d in devices
    ]
    return UserKeyBundleResponse(user_id=user_id, devices=items)


@router.get("/users/{user_id}/key-bundle", response_model=UserKeyBundleResponse)
async def get_user_key_bundle(
    user_id: uuid.UUID,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Bundle всех активных устройств пользователя для X3DH / signal_v1.
    Для каждого device отдаёт не более одного unused one-time prekey (и помечает consumed).
    Для hybrid_device_v0 используйте GET /users/{id}/devices.
    """
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    devices = (
        db.query(Devices)
        .filter(Devices.user_id == user_id, Devices.is_active == True)
        .all()
    )
    items: List[DeviceBundleItem] = []
    now = datetime.now(timezone.utc)
    for d in devices:
        otpk_row = (
            db.query(DeviceOneTimePrekeys)
            .filter(
                DeviceOneTimePrekeys.device_row_id == d.id,
                DeviceOneTimePrekeys.consumed_at.is_(None),
            )
            .order_by(DeviceOneTimePrekeys.key_id.asc())
            .first()
        )
        otpk = None
        if otpk_row:
            otpk_row.consumed_at = now
            otpk = OneTimePrekeyIn(key_id=otpk_row.key_id, public_key=otpk_row.public_key)
        items.append(
            DeviceBundleItem(
                device_id=d.device_id,
                identity_key_public=d.identity_key_public,
                signal_identity_key_public=getattr(d, "signal_identity_key_public", None),
                registration_id=d.registration_id,
                signed_prekey_id=d.signed_prekey_id,
                signed_prekey_public=d.signed_prekey_public,
                signed_prekey_signature=d.signed_prekey_signature,
                one_time_prekey=otpk,
            )
        )
    db.commit()
    return UserKeyBundleResponse(user_id=user_id, devices=items)


def _make_link_code() -> str:
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


@router.post("/devices/link/start", response_model=LinkStartResponse)
async def link_start(
    body: LinkStartRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trusted device creates a short-lived linking code (show as QR / text).
    New device calls /link/finish with the same user JWT + code.
    """
    from datetime import timedelta
    from server.database.DeviceLinkChallenges import DeviceLinkChallenges

    uid = current_user["user_id"]
    creator = (
        db.query(Devices)
        .filter(
            Devices.user_id == uid,
            Devices.device_id == body.device_id,
            Devices.is_active == True,
        )
        .first()
    )
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creator device not found")

    now = datetime.now(timezone.utc)
    code = _make_link_code()
    # uniqueness retry
    for _ in range(5):
        exists = (
            db.query(DeviceLinkChallenges)
            .filter(
                DeviceLinkChallenges.code == code,
                DeviceLinkChallenges.consumed_at.is_(None),
                DeviceLinkChallenges.expires_at > now,
            )
            .first()
        )
        if not exists:
            break
        code = _make_link_code()

    expires = now + timedelta(minutes=10)
    row = DeviceLinkChallenges(
        user_id=uid,
        code=code,
        created_by_device_id=body.device_id,
        expires_at=expires,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return LinkStartResponse(
        link_id=row.id,
        code=code,
        expires_at=expires.isoformat(),
        qr_payload=f"kindred-link:{code}",
    )


@router.post("/devices/link/finish", response_model=LinkFinishResponse)
async def link_finish(
    body: LinkFinishRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """New device (same account JWT) claims a linking code from a trusted device."""
    from server.database.DeviceLinkChallenges import DeviceLinkChallenges

    uid = current_user["user_id"]
    code = body.code.strip().upper()
    now = datetime.now(timezone.utc)
    challenge = (
        db.query(DeviceLinkChallenges)
        .filter(
            DeviceLinkChallenges.user_id == uid,
            DeviceLinkChallenges.code == code,
            DeviceLinkChallenges.consumed_at.is_(None),
        )
        .first()
    )
    if not challenge or challenge.expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired link code")

    if challenge.created_by_device_id == body.device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot link the same device that created the code",
        )

    device = (
        db.query(Devices)
        .filter(
            Devices.user_id == uid,
            Devices.device_id == body.device_id,
            Devices.is_active == True,
        )
        .first()
    )
    if not device:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Register this device before finishing link",
        )

    challenge.consumed_at = now
    challenge.consumed_by_device_id = body.device_id
    device.linked_at = now
    device.last_seen_at = now
    db.commit()
    return LinkFinishResponse(device_id=body.device_id, linked=True)


@router.post("/devices/link/approve-login", response_model=ApproveLoginResponse)
async def approve_login(
    body: ApproveLoginRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trusted mobile scans kindred-login:CODE from desktop auth screen and approves session.
    """
    import json
    from server.api.auth import _create_tokens_and_session
    from server.database.DeviceLoginPending import DeviceLoginPending
    from server.services.device_service import get_active_user, payload_from_dict, upsert_user_device

    uid = current_user["user_id"]
    code = body.code.strip().upper()
    now = datetime.now(timezone.utc)

    approver = (
        db.query(Devices)
        .filter(
            Devices.user_id == uid,
            Devices.device_id == body.device_id,
            Devices.is_active == True,
        )
        .first()
    )
    if not approver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approver device not found")

    pending = (
        db.query(DeviceLoginPending)
        .filter(
            DeviceLoginPending.code == code,
            DeviceLoginPending.consumed_at.is_(None),
        )
        .first()
    )
    if not pending or pending.expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired login code")
    if pending.access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Login already approved")

    try:
        user = get_active_user(db, uid)
        payload = payload_from_dict(json.loads(pending.device_payload_json))
        if payload.device_id == body.device_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot approve login for the same device",
            )
        device = upsert_user_device(db, user.id, payload)
        device.linked_at = now
        device.last_seen_at = now
        access_token, refresh_token = _create_tokens_and_session(db, user, "chatApp")
        pending.user_id = user.id
        pending.approved_by_device_id = body.device_id
        pending.access_token = access_token
        pending.refresh_token = refresh_token
        pending.encrypted_master_key = body.encrypted_master_key
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise

    return ApproveLoginResponse(approved=True, login_device_id=payload.device_id)
