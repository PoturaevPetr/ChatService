"""Parse / validate E2E payloads (signal_v1, sender_key_v0; legacy/hybrid rejected on send)."""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Set, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from server.database.Devices import Devices


PROTOCOL_LEGACY = "legacy_user_e2e"
PROTOCOL_HYBRID_DEVICE = "hybrid_device_v0"
PROTOCOL_SIGNAL = "signal_v1"
PROTOCOL_SENDER_KEY = "sender_key_v0"


def list_active_device_ids_by_user(db: Session, user_ids: Set[uuid.UUID]) -> Dict[uuid.UUID, List[str]]:
    if not user_ids:
        return {}
    rows = (
        db.query(Devices.user_id, Devices.device_id)
        .filter(
            Devices.user_id.in_(user_ids),
            Devices.is_active.is_(True),
            Devices.revoked_at.is_(None),
        )
        .all()
    )
    out: Dict[uuid.UUID, List[str]] = {uid: [] for uid in user_ids}
    for uid, did in rows:
        out.setdefault(uid, []).append(did)
    return out


def parse_e2e_for_send(
    e2e: dict | object,
    member_ids: Set[uuid.UUID],
    db: Session,
) -> Tuple[str, str, Optional[str], str, List[Tuple[uuid.UUID, str]], List[Tuple[uuid.UUID, str, str]]]:
    """
    Returns:
      encrypted_data, nonce, signature, protocol,
      recipient_keys [(user_id, aes_wrap)],
      device_keys [(user_id, device_id, aes_wrap)]
    """
    if hasattr(e2e, "model_dump"):
        data = e2e.model_dump()
    elif isinstance(e2e, dict):
        data = e2e
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="e2e must be an object")

    enc = data.get("encrypted_data")
    nonce = data.get("nonce")
    signature = data.get("signature")
    protocol = (data.get("protocol") or PROTOCOL_LEGACY).strip() or PROTOCOL_LEGACY
    envelopes = data.get("envelopes") or []
    recipient_keys_raw = data.get("recipient_keys") or []

    if protocol == PROTOCOL_SIGNAL or (
        isinstance(envelopes, list)
        and envelopes
        and any(isinstance(e, dict) and e.get("type") in ("prekey", "message") for e in envelopes)
        and protocol != PROTOCOL_SENDER_KEY
    ):
        protocol = PROTOCOL_SIGNAL
        if not isinstance(enc, str):
            enc = ""
        if not isinstance(nonce, str):
            nonce = ""
        if not isinstance(envelopes, list) or not envelopes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="e2e.envelopes required for signal_v1",
            )
        device_rows = (
            db.query(Devices)
            .filter(
                Devices.user_id.in_(member_ids),
                Devices.is_active.is_(True),
                Devices.revoked_at.is_(None),
            )
            .all()
        )
        device_to_user = {d.device_id: d.user_id for d in device_rows}
        required_devices = set(device_to_user.keys())
        if not required_devices:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No registered devices for room members",
            )
        seen: Set[str] = set()
        device_keys: List[Tuple[uuid.UUID, str, str]] = []
        for env in envelopes:
            if not isinstance(env, dict):
                continue
            did = env.get("device_id")
            body = env.get("body_b64") or env.get("encrypted_aes_key")
            if not isinstance(did, str) or not isinstance(body, str):
                continue
            uid = device_to_user.get(did)
            if uid is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown or inactive device_id in envelopes: {did}",
                )
            seen.add(did)
            device_keys.append((uid, did, body))
        missing = required_devices - seen
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"e2e.envelopes must include every active device ({len(missing)} missing)",
            )
        by_user: Dict[uuid.UUID, str] = {}
        for uid, _did, body in device_keys:
            by_user.setdefault(uid, body)
        if set(by_user.keys()) != member_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="e2e.envelopes must cover every room member",
            )
        return (
            enc,
            nonce,
            signature if isinstance(signature, str) else None,
            protocol,
            list(by_user.items()),
            device_keys,
        )

    if protocol == PROTOCOL_HYBRID_DEVICE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hybrid_device_v0 removed; use signal_v1 or sender_key_v0",
        )

    if not isinstance(enc, str) or not isinstance(nonce, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="e2e.encrypted_data and e2e.nonce are required",
        )

    device_keys: List[Tuple[uuid.UUID, str, str]] = []
    recipient_keys: List[Tuple[uuid.UUID, str]] = []

    if protocol == PROTOCOL_SENDER_KEY or (
        isinstance(envelopes, list)
        and len(envelopes) > 0
        and any(isinstance(e, dict) and e.get("type") in ("skdm", "sender_key") for e in envelopes)
    ):
        protocol = PROTOCOL_SENDER_KEY
        if not isinstance(envelopes, list) or not envelopes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="e2e.envelopes required for sender_key_v0",
            )

        # Map device_id -> user_id from active devices of members
        device_rows = (
            db.query(Devices)
            .filter(
                Devices.user_id.in_(member_ids),
                Devices.is_active.is_(True),
                Devices.revoked_at.is_(None),
            )
            .all()
        )
        device_to_user = {d.device_id: d.user_id for d in device_rows}
        required_devices = set(device_to_user.keys())
        if not required_devices:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No registered devices for room members; each user must register a device",
            )

        seen: Set[str] = set()
        for env in envelopes:
            if not isinstance(env, dict):
                continue
            did = env.get("device_id")
            body = env.get("body_b64") or env.get("encrypted_aes_key")
            if not isinstance(did, str) or not isinstance(body, str):
                continue
            uid = device_to_user.get(did)
            if uid is None:
                # allow explicit user_id on envelope for forward-compat
                uid_raw = env.get("user_id")
                if isinstance(uid_raw, str):
                    try:
                        uid = uuid.UUID(uid_raw)
                    except ValueError:
                        uid = None
                if uid is None or uid not in member_ids:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown or inactive device_id in envelopes: {did}",
                    )
            seen.add(did)
            device_keys.append((uid, did, body))

        missing = required_devices - seen
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"e2e.envelopes must include every active device ({len(missing)} missing)",
            )
        extra = seen - required_devices
        if extra:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="e2e.envelopes contains unknown device_id",
            )

        # Derive one recipient_key per member (access gate + legacy field)
        by_user: Dict[uuid.UUID, str] = {}
        for uid, _did, body in device_keys:
            by_user.setdefault(uid, body)
        if set(by_user.keys()) != member_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="e2e.envelopes must cover every room member",
            )
        recipient_keys = list(by_user.items())
        return enc, nonce, signature if isinstance(signature, str) else None, protocol, recipient_keys, device_keys

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="legacy_user_e2e / hybrid removed; use protocol signal_v1 or sender_key_v0 with envelopes",
    )
