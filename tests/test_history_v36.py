"""V3.6 encrypted history blob API."""

from __future__ import annotations


def test_history_blob_upload_list_download(client, register_user):
    user = register_user()
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    up = client.post(
        "/api/v1/history/blobs",
        headers=headers,
        json={
            "source_device_id": "device-aaaaaaaa",
            "ciphertext": "Y2lwaGVyLWZvci1oaXN0b3J5LXBhY2stdGVzdA==",
            "nonce_b64": "bm9uY2UxMjM0NTY=",
            "meta_json": '{"rooms":1}',
            "ttl_hours": 24,
        },
    )
    assert up.status_code == 201, up.text
    blob_id = up.json()["id"]

    listed = client.get("/api/v1/history/blobs", headers=headers)
    assert listed.status_code == 200
    assert any(b["id"] == blob_id for b in listed.json())

    got = client.get(f"/api/v1/history/blobs/{blob_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["ciphertext"].startswith("Y2lw")

    deleted = client.delete(f"/api/v1/history/blobs/{blob_id}", headers=headers)
    assert deleted.status_code == 204
