"""Accept signal_v1 envelopes (empty shared AES body)."""

from __future__ import annotations

import uuid


def test_send_signal_v1_envelopes(client, register_user, public_key_pem, monkeypatch):
    from server.services import notification_service as ns

    async def _noop_deliver(*_a, **_k):
        return None

    monkeypatch.setattr(
        ns.NotificationService,
        "deliver_new_message_to_recipient",
        staticmethod(_noop_deliver),
    )

    a = register_user()
    b = register_user()
    a_dev = str(uuid.uuid4())
    b_dev = str(uuid.uuid4())
    for user, did in ((a, a_dev), (b, b_dev)):
        r = client.post(
            "/api/v1/devices/register",
            headers={"Authorization": f"Bearer {user['access_token']}"},
            json={
                "device_id": did,
                "platform": "web",
                "identity_key_public": public_key_pem,
                "signal_identity_key_public": "c2lnbmFsLWlkZW50aXR5LWtleQ==",
                "registration_id": 7,
                "signed_prekey_id": 1,
                "signed_prekey_public": "c2lnbmVkLXByZWtleQ==",
                "signed_prekey_signature": "c2lnbmF0dXJl",
            },
        )
        assert r.status_code == 201, r.text

    fake_body = '{"v":1,"msgType":3,"body_b64":"YWJj","sender_user_id":"%s","sender_device_id":"%s"}' % (
        a["user_id"],
        a_dev,
    )
    e2e = {
        "protocol": "signal_v1",
        "encrypted_data": "",
        "nonce": "",
        "envelopes": [
            {"device_id": a_dev, "type": "prekey", "body_b64": fake_body, "user_id": a["user_id"]},
            {"device_id": b_dev, "type": "prekey", "body_b64": fake_body, "user_id": b["user_id"]},
        ],
        "recipient_keys": [
            {"user_id": a["user_id"], "encrypted_aes_key": fake_body},
            {"user_id": b["user_id"], "encrypted_aes_key": fake_body},
        ],
    }
    send = client.post(
        "/api/v1/messages/",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={"recipient_id": b["user_id"], "e2e": e2e},
    )
    assert send.status_code == 201, send.text
    mid = send.json()["message_id"]
    got = client.get(
        f"/api/v1/messages/{mid}",
        headers={"Authorization": f"Bearer {b['access_token']}", "X-Device-Id": b_dev},
    )
    assert got.status_code == 200, got.text
    assert got.json()["encrypted_data"] == ""
    assert any(e["device_id"] == b_dev for e in got.json()["device_envelopes"])


def test_list_messages_with_device_id_returns_signal_envelope(client, register_user, public_key_pem, monkeypatch):
    from server.services import notification_service as ns

    async def _noop_deliver(*_a, **_k):
        return None

    monkeypatch.setattr(
        ns.NotificationService,
        "deliver_new_message_to_recipient",
        staticmethod(_noop_deliver),
    )

    a = register_user()
    b = register_user()
    a_dev = str(uuid.uuid4())
    b_dev = str(uuid.uuid4())
    b_dev_other = str(uuid.uuid4())
    for user, did in ((a, a_dev), (b, b_dev), (b, b_dev_other)):
        r = client.post(
            "/api/v1/devices/register",
            headers={"Authorization": f"Bearer {user['access_token']}"},
            json={
                "device_id": did,
                "platform": "web",
                "identity_key_public": public_key_pem,
                "signal_identity_key_public": "c2lnbmFsLWlkZW50aXR5LWtleQ==",
                "registration_id": 7,
                "signed_prekey_id": 1,
                "signed_prekey_public": "c2lnbmVkLXByZWtleQ==",
                "signed_prekey_signature": "c2lnbmF0dXJl",
            },
        )
        assert r.status_code == 201, r.text

    fake_body = '{"v":1,"msgType":3,"body_b64":"YWJj","sender_user_id":"%s","sender_device_id":"%s"}' % (
        a["user_id"],
        a_dev,
    )
    e2e = {
        "protocol": "signal_v1",
        "encrypted_data": "",
        "nonce": "",
        "envelopes": [
            {"device_id": a_dev, "type": "prekey", "body_b64": fake_body, "user_id": a["user_id"]},
            {"device_id": b_dev, "type": "prekey", "body_b64": fake_body, "user_id": b["user_id"]},
            {"device_id": b_dev_other, "type": "prekey", "body_b64": fake_body, "user_id": b["user_id"]},
        ],
        "recipient_keys": [
            {"user_id": a["user_id"], "encrypted_aes_key": fake_body},
            {"user_id": b["user_id"], "encrypted_aes_key": fake_body},
        ],
    }
    send = client.post(
        "/api/v1/messages/",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={"recipient_id": b["user_id"], "e2e": e2e},
    )
    assert send.status_code == 201, send.text

    listed = client.get(
        "/api/v1/messages/",
        headers={"Authorization": f"Bearer {b['access_token']}", "X-Device-Id": b_dev_other},
        params={"limit": 10, "offset": 0},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert len(items) >= 1
    row = items[0]
    assert row["encrypted_data"] == ""
    assert row["encrypted_aes_key"]
    assert any(e["device_id"] == b_dev_other for e in (row.get("device_envelopes") or []))
