"""Shared device registration / linking logic (CRYPTO_DEVICES_V3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

from server.database.Devices import Devices, DeviceOneTimePrekeys
from server.database.DeviceLinkChallenges import DeviceLinkChallenges
from server.database.Users import Users


class DeviceRegisterPayload:
    """Plain payload mirror of DeviceRegisterRequest (avoids circular API imports)."""

    def __init__(
        self,
        *,
        device_id: str,
        name: Optional[str],
        platform: str,
        identity_key_public: str,
        signal_identity_key_public: Optional[str],
        registration_id: int,
        signed_prekey_id: Optional[int],
        signed_prekey_public: Optional[str],
        signed_prekey_signature: Optional[str],
        one_time_prekeys: list,
    ):
        self.device_id = device_id
        self.name = name
        self.platform = platform
        self.identity_key_public = identity_key_public
        self.signal_identity_key_public = signal_identity_key_public
        self.registration_id = registration_id
        self.signed_prekey_id = signed_prekey_id
        self.signed_prekey_public = signed_prekey_public
        self.signed_prekey_signature = signed_prekey_signature
        self.one_time_prekeys = one_time_prekeys


def upsert_user_device(db: Session, uid: uuid.UUID, body: DeviceRegisterPayload) -> Devices:
    """Register or update an active device row for the user."""
    now = datetime.now(timezone.utc)
    platform = (body.platform or "web").strip().lower() or "web"

    row = (
        db.query(Devices)
        .filter(Devices.user_id == uid, Devices.device_id == body.device_id)
        .first()
    )
    if row:
        row.name = body.name
        row.platform = platform
        row.identity_key_public = body.identity_key_public.strip()
        if body.signal_identity_key_public:
            row.signal_identity_key_public = body.signal_identity_key_public.strip()
        row.registration_id = body.registration_id
        row.signed_prekey_id = body.signed_prekey_id
        row.signed_prekey_public = body.signed_prekey_public
        row.signed_prekey_signature = body.signed_prekey_signature
        row.is_active = True
        row.revoked_at = None
        row.last_seen_at = now
    else:
        row = Devices(
            user_id=uid,
            device_id=body.device_id.strip(),
            name=body.name,
            platform=platform,
            identity_key_public=body.identity_key_public.strip(),
            signal_identity_key_public=(body.signal_identity_key_public or "").strip() or None,
            registration_id=body.registration_id,
            signed_prekey_id=body.signed_prekey_id,
            signed_prekey_public=body.signed_prekey_public,
            signed_prekey_signature=body.signed_prekey_signature,
            is_active=True,
            last_seen_at=now,
            created_at=now,
        )
        db.add(row)
        db.flush()

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
            if exists.consumed_at is None:
                exists.public_key = otpk.public_key
            continue
        db.add(
            DeviceOneTimePrekeys(
                device_row_id=row.id,
                key_id=otpk.key_id,
                public_key=otpk.public_key,
            )
        )

    # First device for this user → auto-linked (primary)
    if getattr(row, "linked_at", None) is None:
        others = (
            db.query(Devices)
            .filter(Devices.user_id == uid, Devices.is_active == True, Devices.id != row.id)
            .count()
        )
        if others == 0:
            row.linked_at = now

    return row


def consume_link_challenge(
    db: Session,
    *,
    user_id: uuid.UUID,
    code: str,
    new_device_id: str,
) -> DeviceLinkChallenges:
    """Validate code and mark consumed; does not commit."""
    normalized = code.strip().upper()
    now = datetime.now(timezone.utc)
    challenge = (
        db.query(DeviceLinkChallenges)
        .filter(
            DeviceLinkChallenges.user_id == user_id,
            DeviceLinkChallenges.code == normalized,
            DeviceLinkChallenges.consumed_at.is_(None),
        )
        .first()
    )
    if not challenge or challenge.expires_at < now:
        raise ValueError("Invalid or expired link code")

    if challenge.created_by_device_id == new_device_id:
        raise ValueError("Cannot link the same device that created the code")

    challenge.consumed_at = now
    challenge.consumed_by_device_id = new_device_id
    return challenge


def get_active_user(db: Session, user_id: uuid.UUID) -> Users:
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user or not user.is_active:
        raise ValueError("User account is disabled")
    return user


def make_link_code() -> str:
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def payload_from_dict(data: dict) -> DeviceRegisterPayload:
    raw_otpks = data.get("one_time_prekeys") or []


    class _Otpk:
        def __init__(self, key_id: int, public_key: str):
            self.key_id = key_id
            self.public_key = public_key

    otpks = [_Otpk(int(p["key_id"]), str(p["public_key"])) for p in raw_otpks]
    return DeviceRegisterPayload(
        device_id=str(data["device_id"]),
        name=data.get("name"),
        platform=str(data.get("platform") or "web"),
        identity_key_public=str(data["identity_key_public"]),
        signal_identity_key_public=data.get("signal_identity_key_public"),
        registration_id=int(data.get("registration_id") or 0),
        signed_prekey_id=data.get("signed_prekey_id"),
        signed_prekey_public=data.get("signed_prekey_public"),
        signed_prekey_signature=data.get("signed_prekey_signature"),
        one_time_prekeys=otpks,
    )


def payload_to_dict(body: DeviceRegisterPayload) -> dict:
    return {
        "device_id": body.device_id,
        "name": body.name,
        "platform": body.platform,
        "identity_key_public": body.identity_key_public,
        "signal_identity_key_public": body.signal_identity_key_public,
        "registration_id": body.registration_id,
        "signed_prekey_id": body.signed_prekey_id,
        "signed_prekey_public": body.signed_prekey_public,
        "signed_prekey_signature": body.signed_prekey_signature,
        "one_time_prekeys": [
            {"key_id": p.key_id, "public_key": p.public_key} for p in (body.one_time_prekeys or [])
        ],
    }
