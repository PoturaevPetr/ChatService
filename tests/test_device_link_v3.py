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
