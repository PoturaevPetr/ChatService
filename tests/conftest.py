"""Shared fixtures: Postgres test DB (or TEST_DATABASE_URL), flags, TestClient."""

from __future__ import annotations

import os
import uuid
from typing import Generator

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from server import app
from server.database import Base, get_db
from server.settings import settings

DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@127.0.0.1:5434/ChatDatabase_test"


def _rsa_public_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )


@pytest.fixture
def public_key_pem() -> str:
    return _rsa_public_pem()


@pytest.fixture
def v2_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stable JWT + internal secret for tests."""
    monkeypatch.setattr(settings, "INTERNAL_DELIVERY_SECRET", "test-internal-secret", raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-jwt-secret-key-for-pytest", raising=False)


@pytest.fixture(scope="session")
def test_engine():
    url = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL).strip()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(
            f"Postgres test DB unavailable ({url}). "
            f"Start ChatService docker postgres or set TEST_DATABASE_URL. ({exc})"
        )

    import server.database.Users  # noqa: F401
    import server.database.Sessions  # noqa: F401
    import server.database.Messages  # noqa: F401
    import server.database.Rooms  # noqa: F401
    import server.database.APIKeys  # noqa: F401
    import server.database.RoomUsers  # noqa: F401
    import server.database.MessageRecipientKeys  # noqa: F401
    import server.database.MessageDeviceKeys  # noqa: F401
    import server.database.MessageReads  # noqa: F401
    import server.database.Devices  # noqa: F401
    import server.database.DeviceLinkChallenges  # noqa: F401
    import server.database.EncryptedHistoryBlobs  # noqa: F401
    import server.database.MessageReactions  # noqa: F401
    import server.database.Attachments  # noqa: F401
    import server.database.MobileAppReleases  # noqa: F401
    import server.database.OAuthAccounts  # noqa: F401
    import server.database.UserKeyBackups  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine, v2_flags) -> Generator[Session, None, None]:
    connection = test_engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = TestingSessionLocal()
    # Nested transaction so route commits don't persist across tests
    session.begin_nested()

    from sqlalchemy import event

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session, v2_flags) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    startup = list(getattr(app.router, "on_startup", []) or [])
    shutdown = list(getattr(app.router, "on_shutdown", []) or [])
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    app.router.on_startup.extend(startup)
    app.router.on_shutdown.extend(shutdown)


@pytest.fixture
def register_user(client: TestClient):
    def _register(
        username: str | None = None,
        password: str = "TestPass123!",
        public_key: str | None = None,
    ) -> dict:
        name = username or f"u_{uuid.uuid4().hex[:12]}"
        body = {
            "username": name,
            "service_id": "chatApp",
            "password": password,
        }
        if public_key:
            body["public_key"] = public_key  # ignored by API; kept for call-site compat
        resp = client.post("/api/v1/auth/register", json=body)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        data["_username"] = name
        return data

    return _register
