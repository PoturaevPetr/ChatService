"""API tests for CRYPTO_DEVICES_V3 device registry."""

from __future__ import annotations

import uuid


def test_register_and_list_device(client, register_user, public_key_pem):
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    device_id = str(uuid.uuid4())
    r = client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": device_id,
            "name": "Test Phone",
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 42,
            "one_time_prekeys": [
                {"key_id": 1, "public_key": public_key_pem},
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["device_id"] == device_id
    assert "BEGIN PUBLIC KEY" in body["identity_key_public"]

    listed = client.get("/api/v1/devices/me", headers=headers)
    assert listed.status_code == 200
    assert any(d["device_id"] == device_id for d in listed.json())


def test_key_bundle_consumes_one_time_prekey(client, register_user, public_key_pem):
    a = register_user()
    b = register_user()
    headers_b = {"Authorization": f"Bearer {b['access_token']}"}
    device_id = str(uuid.uuid4())
    # fresh key for OTP distinctness not required for this API
    client.post(
        "/api/v1/devices/register",
        headers=headers_b,
        json={
            "device_id": device_id,
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 1,
            "one_time_prekeys": [{"key_id": 7, "public_key": public_key_pem}],
        },
    )

    headers_a = {"Authorization": f"Bearer {a['access_token']}"}
    bundle = client.get(f"/api/v1/users/{b['user_id']}/key-bundle", headers=headers_a)
    assert bundle.status_code == 200, bundle.text
    devices = bundle.json()["devices"]
    assert len(devices) >= 1
    d0 = next(d for d in devices if d["device_id"] == device_id)
    assert d0["one_time_prekey"] is not None
    assert d0["one_time_prekey"]["key_id"] == 7

    # second fetch — OTP consumed
    bundle2 = client.get(f"/api/v1/users/{b['user_id']}/key-bundle", headers=headers_a)
    d0b = next(d for d in bundle2.json()["devices"] if d["device_id"] == device_id)
    assert d0b["one_time_prekey"] is None


def test_list_user_devices_does_not_consume_otpk(client, register_user, public_key_pem):
    a = register_user()
    b = register_user()
    headers_b = {"Authorization": f"Bearer {b['access_token']}"}
    device_id = str(uuid.uuid4())
    client.post(
        "/api/v1/devices/register",
        headers=headers_b,
        json={
            "device_id": device_id,
            "platform": "web",
            "identity_key_public": public_key_pem,
            "registration_id": 1,
            "one_time_prekeys": [{"key_id": 3, "public_key": public_key_pem}],
        },
    )
    headers_a = {"Authorization": f"Bearer {a['access_token']}"}
    listed = client.get(f"/api/v1/users/{b['user_id']}/devices", headers=headers_a)
    assert listed.status_code == 200, listed.text
    d0 = next(d for d in listed.json()["devices"] if d["device_id"] == device_id)
    assert d0["one_time_prekey"] is None
    assert "BEGIN PUBLIC KEY" in d0["identity_key_public"]

    # OTP still available for key-bundle
    bundle = client.get(f"/api/v1/users/{b['user_id']}/key-bundle", headers=headers_a)
    d1 = next(d for d in bundle.json()["devices"] if d["device_id"] == device_id)
    assert d1["one_time_prekey"]["key_id"] == 3


def test_revoke_device(client, register_user, public_key_pem):
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    device_id = str(uuid.uuid4())
    client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={
            "device_id": device_id,
            "platform": "ios",
            "identity_key_public": public_key_pem,
            "registration_id": 1,
        },
    )
    rev = client.delete(f"/api/v1/devices/{device_id}", headers=headers)
    assert rev.status_code == 204
    listed = client.get("/api/v1/devices/me", headers=headers)
    assert not any(d["device_id"] == device_id for d in listed.json())
