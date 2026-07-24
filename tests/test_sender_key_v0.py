"""sender_key_v0 group envelopes accepted by message API."""

from __future__ import annotations

import uuid


def test_send_sender_key_v0(client, register_user, public_key_pem, monkeypatch):
    from server.services import notification_service as ns

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(
        ns.NotificationService,
        "deliver_new_message_to_recipient",
        staticmethod(_noop),
    )

    a = register_user()
    b = register_user()
    c = register_user()
    devices = {}
    for user in (a, b, c):
        did = str(uuid.uuid4())
        devices[user["user_id"]] = did
        r = client.post(
            "/api/v1/devices/register",
            headers={"Authorization": f"Bearer {user['access_token']}"},
            json={
                "device_id": did,
                "platform": "web",
                "identity_key_public": public_key_pem,
                "registration_id": 1,
            },
        )
        assert r.status_code == 201, r.text

    # Create group room with a,b,c
    room = client.post(
        "/api/v1/rooms/",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={
            "name": "SK Group",
            "member_user_ids": [b["user_id"], c["user_id"]],
        },
    )
    assert room.status_code in (200, 201), room.text
    room_id = room.json()["id"]

    meta = (
        '{"v":1,"t":"sender_key","room_id":"%s","sender_user_id":"%s",'
        '"sender_device_id":"%s","key_id":1,"iteration":0}'
        % (room_id, a["user_id"], devices[a["user_id"]])
    )
    e2e = {
        "protocol": "sender_key_v0",
        "encrypted_data": "Z3JvdXAtY3Q=",
        "nonce": "bm9uY2UxMjM0NTY=",
        "envelopes": [
            {
                "device_id": devices[uid],
                "type": "sender_key",
                "body_b64": meta,
                "user_id": uid,
            }
            for uid in (a["user_id"], b["user_id"], c["user_id"])
        ],
        "recipient_keys": [
            {"user_id": uid, "encrypted_aes_key": meta}
            for uid in (a["user_id"], b["user_id"], c["user_id"])
        ],
    }
    send = client.post(
        "/api/v1/messages/",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={"room_id": room_id, "e2e": e2e},
    )
    assert send.status_code == 201, send.text
