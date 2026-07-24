"""API contract tests — greenfield V3: devices + Signal/sender_key, no user_keys messaging."""

from __future__ import annotations

import uuid


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_register_without_public_key(client):
    r = client.post(
        "/api/v1/auth/register",
        json={
            "username": f"no_pk_{uuid.uuid4().hex[:8]}",
            "service_id": "chatApp",
            "password": "TestPass123!",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json().get("access_token")
    assert r.json().get("public_key") in (None, "")


def test_register_no_private_on_wire(register_user):
    data = register_user()
    assert "private_key" not in data or data.get("private_key") is None
    assert data.get("access_token")


def test_keypair_route_gone(client, register_user):
    user = register_user()
    r = client.get(
        "/api/v1/keys/me/keypair",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 404


def test_public_key_routes_gone(client, register_user):
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    assert client.get("/api/v1/keys/me/public", headers=headers).status_code == 410
    assert (
        client.get(f"/api/v1/keys/public/{user['user_id']}", headers=headers).status_code == 410
    )


def test_internal_deliver_gone(client):
    r = client.post(
        "/api/internal/deliver",
        headers={"X-Internal-Secret": "test-internal-secret"},
        json={},
    )
    assert r.status_code == 404


def test_plain_message_route_gone(client, register_user):
    user = register_user()
    r = client.post(
        "/api/v1/messages/plain",
        headers={"Authorization": f"Bearer {user['access_token']}"},
        json={"recipient_id": str(uuid.uuid4()), "text": "hi"},
    )
    assert r.status_code in (404, 405)


def test_attachment_decrypted_route_gone(client, register_user):
    user = register_user()
    r = client.get(
        f"/api/v1/attachments/{uuid.uuid4()}/decrypted",
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert r.status_code == 404


def test_send_message_requires_e2e_payload(client, register_user):
    user = register_user()
    r = client.post(
        "/api/v1/messages/",
        headers={"Authorization": f"Bearer {user['access_token']}"},
        json={"recipient_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422


def test_legacy_e2e_rejected(client, register_user, monkeypatch):
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
    r = client.post(
        "/api/v1/messages/",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={
            "recipient_id": b["user_id"],
            "e2e": {
                "encrypted_data": "ZW5j",
                "nonce": "bm9uY2U=",
                "recipient_keys": [
                    {"user_id": a["user_id"], "encrypted_aes_key": "a2V5YQ=="},
                    {"user_id": b["user_id"], "encrypted_aes_key": "a2V5Yg=="},
                ],
            },
        },
    )
    assert r.status_code == 400, r.text


def test_key_backup_put_get(client, register_user):
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    payload = {
        "ciphertext": "Y2lwaGVyLWJhY2t1cC1kYXRhLXRlc3Q=",
        "kdf": "pbkdf2-sha256",
        "kdf_salt_b64": "c2FsdC1mb3ItdGVzdA==",
        "kdf_params": {"iterations": 310000},
        "wrap_alg": "aes-256-gcm",
        "nonce_b64": "bm9uY2UxMjM0NTY=",
    }
    put = client.put("/api/v1/keys/me/backup", headers=headers, json=payload)
    assert put.status_code in (200, 201), put.text

    get = client.get("/api/v1/keys/me/backup", headers=headers)
    assert get.status_code == 200, get.text
    data = get.json()
    assert data["ciphertext"] == payload["ciphertext"]
    assert data["kdf_salt_b64"] == payload["kdf_salt_b64"]
    assert data["nonce_b64"] == payload["nonce_b64"]
