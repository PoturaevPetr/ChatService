"""V3.3 device linking + unused OTP count on /devices/me."""

from __future__ import annotations

import uuid


def test_link_start_finish_and_otpk_count(client, register_user, public_key_pem):
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    a_dev = str(uuid.uuid4())
    b_dev = str(uuid.uuid4())

    r = client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": a_dev,
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 1,
            "one_time_prekeys": [
                {"key_id": 1, "public_key": public_key_pem},
                {"key_id": 2, "public_key": public_key_pem},
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json().get("linked_at")  # first device auto-linked

    client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": b_dev,
            "platform": "ios",
            "identity_key_public": public_key_pem,
            "registration_id": 2,
        },
    )

    listed = client.get("/api/v1/devices/me", headers=headers)
    assert listed.status_code == 200
    a_row = next(d for d in listed.json() if d["device_id"] == a_dev)
    assert a_row["unused_otpk_count"] == 2

    start = client.post(
        "/api/v1/devices/link/start",
        headers=headers,
        json={"device_id": a_dev},
    )
    assert start.status_code == 200, start.text
    code = start.json()["code"]
    assert start.json()["qr_payload"].startswith("kindred-link:")

    finish = client.post(
        "/api/v1/devices/link/finish",
        headers=headers,
        json={"code": code, "device_id": b_dev},
    )
    assert finish.status_code == 200, finish.text
    assert finish.json()["linked"] is True

    listed2 = client.get("/api/v1/devices/me", headers=headers)
    b_row = next(d for d in listed2.json() if d["device_id"] == b_dev)
    assert b_row.get("linked_at")

    # reuse code → fail
    again = client.post(
        "/api/v1/devices/link/finish",
        headers=headers,
        json={"code": code, "device_id": b_dev},
    )
    assert again.status_code == 400


def test_device_link_exchange_unauthenticated(client, register_user, public_key_pem):
    """New device logs in via QR code without prior JWT."""
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    trusted_dev = str(uuid.uuid4())
    new_dev = str(uuid.uuid4())

    reg = client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": trusted_dev,
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 1,
        },
    )
    assert reg.status_code == 201, reg.text

    start = client.post(
        "/api/v1/devices/link/start",
        headers=headers,
        json={"device_id": trusted_dev},
    )
    assert start.status_code == 200, start.text
    code = start.json()["code"]

    exchange = client.post(
        "/api/v1/auth/device-link/exchange",
        json={
            "code": code,
            "service_id": "chatApp",
            "device_id": new_dev,
            "platform": "android",
            "identity_key_public": public_key_pem,
            "registration_id": 3,
            "one_time_prekeys": [{"key_id": 1, "public_key": public_key_pem}],
        },
    )
    assert exchange.status_code == 200, exchange.text
    body = exchange.json()
    assert body.get("access_token")
    assert body.get("refresh_token")
    assert body.get("linked") is True
    assert body.get("device_id") == new_dev
    assert str(body.get("user_id")) == str(user["user_id"])

    me = client.get("/api/v1/devices/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    row = next(d for d in me.json() if d["device_id"] == new_dev)
    assert row.get("linked_at")

    reuse = client.post(
        "/api/v1/auth/device-link/exchange",
        json={
            "code": code,
            "service_id": "chatApp",
            "device_id": str(uuid.uuid4()),
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 4,
        },
    )
    assert reuse.status_code == 400


def test_desktop_device_link_request_and_mobile_approval(client, register_user, public_key_pem):
    """
    Гибридный сценарий подтверждения через QR:
    1. Новое устройство вызывает /auth/device-link/request (генерирует QR-код).
    2. Доверенное устройство подтверждает /devices/link/approve-login.
    3. Новое устройство через poll получает статус approved и токены.
    """
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    trusted_dev = str(uuid.uuid4())
    new_dev = str(uuid.uuid4())

    # Регистрируем доверенное устройство
    reg = client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": trusted_dev,
            "platform": "ios",
            "identity_key_public": public_key_pem,
            "registration_id": 1,
        },
    )
    assert reg.status_code == 201

    # 1. Новое устройство запрашивает связывание (показ QR-кода)
    req = client.post(
        "/api/v1/auth/device-link/request",
        json={
            "device_id": new_dev,
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 2,
            "one_time_prekeys": [{"key_id": 1, "public_key": public_key_pem}],
        },
    )
    assert req.status_code == 200, req.text
    req_body = req.json()
    assert req_body.get("request_id")
    code = req_body["code"]
    request_id = req_body["request_id"]
    assert req_body["qr_payload"] == f"kindred-login:{code}"

    # До подтверждения poll возвращает pending
    poll_pending = client.get(f"/api/v1/auth/device-link/poll/{request_id}")
    assert poll_pending.status_code == 200
    assert poll_pending.json()["status"] == "pending"

    # 2. Доверенное устройство сканирует QR и подтверждает вход
    approve = client.post(
        "/api/v1/devices/link/approve-login",
        headers=headers,
        json={
            "code": code,
            "device_id": trusted_dev,
        },
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["approved"] is True
    assert approve.json()["login_device_id"] == new_dev

    # 3. Новое устройство проверяет статус и получает токены
    poll_approved = client.get(f"/api/v1/auth/device-link/poll/{request_id}")
    assert poll_approved.status_code == 200
    poll_body = poll_approved.json()
    assert poll_body["status"] == "approved"
    assert poll_body.get("access_token")
    assert poll_body.get("refresh_token")
    assert str(poll_body["user_id"]) == str(user["user_id"])

    # Повторный poll возвращает expired (токены уже забрали)
    poll_after = client.get(f"/api/v1/auth/device-link/poll/{request_id}")
    assert poll_after.status_code == 200
    assert poll_after.json()["status"] == "expired"


def test_device_key_backup_lifecycle(client, register_user):
    """
    Жизненный цикл облачного резервного бэкапа ключей:
    1. Проверка 404, если бэкап еще не создавался.
    2. Сохранение PUT /keys/me/backup.
    3. Получение GET /keys/me/backup и проверка целостности полей.
    4. Обновление бэкапа и проверка ротации.
    """
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    # 1. До создания бэкапа — 404
    get_empty = client.get("/api/v1/keys/me/backup", headers=headers)
    assert get_empty.status_code == 404

    # 2. Сохраняем первичный бэкап
    payload1 = {
        "ciphertext": "Y2lwaGVydGV4dF9kYXRhXzE=",
        "kdf": "pbkdf2-sha256",
        "kdf_salt_b64": "c2FsdF8xMjM0NQ==",
        "kdf_params": {"iterations": 310000},
        "wrap_alg": "aes-256-gcm",
        "nonce_b64": "bm9uY2VfMTIzNDU2",
    }
    put1 = client.put("/api/v1/keys/me/backup", headers=headers, json=payload1)
    assert put1.status_code == 200
    assert put1.json()["ciphertext"] == payload1["ciphertext"]

    # 3. Читаем сохраненный бэкап
    get1 = client.get("/api/v1/keys/me/backup", headers=headers)
    assert get1.status_code == 200
    assert get1.json()["ciphertext"] == payload1["ciphertext"]
    assert get1.json()["kdf_salt_b64"] == payload1["kdf_salt_b64"]
    assert get1.json()["nonce_b64"] == payload1["nonce_b64"]

    # 4. Обновление (ротация пароля / ключа)
    payload2 = {
        "ciphertext": "Y2lwaGVydGV4dF9kYXRhXzJfdXBkYXRlZA==",
        "kdf": "pbkdf2-sha256",
        "kdf_salt_b64": "c2FsdF85ODc2NQ==",
        "kdf_params": {"iterations": 310000},
        "wrap_alg": "aes-256-gcm",
        "nonce_b64": "bm9uY2VfOTg3NjU0",
    }
    put2 = client.put("/api/v1/keys/me/backup", headers=headers, json=payload2)
    assert put2.status_code == 200

    get2 = client.get("/api/v1/keys/me/backup", headers=headers)
    assert get2.status_code == 200
    assert get2.json()["ciphertext"] == payload2["ciphertext"]
    assert get2.json()["kdf_salt_b64"] == payload2["kdf_salt_b64"]

