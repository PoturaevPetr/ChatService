from sqlalchemy.orm import declarative_base

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from server.settings import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create a shared Base for all models
Base = declarative_base()


def apply_schema_patches() -> None:
    """Idempotent DDL: V3 columns on existing tables + legacy cleanup."""
    patches = [
        # V3 devices — create_all does not ALTER existing `devices` rows/tables
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS signal_identity_key_public TEXT",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS linked_at TIMESTAMPTZ",
        "ALTER TABLE room_user ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT true",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_enabled BOOLEAN DEFAULT false",
        # V2/V3 legacy cleanup (safe when tables absent — IF EXISTS / IF NOT EXISTS)
        "ALTER TABLE users DROP COLUMN IF EXISTS keys_migrated_v2",
        "ALTER TABLE attachments DROP COLUMN IF EXISTS server_decrypt_key_b64",
        "ALTER TABLE attachments DROP COLUMN IF EXISTS server_decrypt_nonce_b64",
        "DROP TABLE IF EXISTS user_keys CASCADE",
    ]
    with engine.begin() as conn:
        for stmt in patches:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                # attachments/users may be missing on minimal test DB — skip non-fatal alters
                msg = str(exc).lower()
                if "does not exist" in msg and "relation" in msg:
                    continue
                raise


def apply_legacy_schema_patches() -> None:
    """Back-compat alias."""
    apply_schema_patches()


def init_db():
    """Инициализация базы данных - создание таблиц при запуске сервера.
    Импорт моделей регистрирует их в Base.metadata; create_all создаёт все таблицы,
    в том числе message_recipient_keys (MessageRecipientKeys).
    """
    from server.database.Users import Users
    # UserKeys dropped in V3.5 (v35_v36_drop_user_keys_history.sql) — do not create_all
    from server.database.Sessions import Sessions
    from server.database.Messages import Messages
    from server.database.Rooms import Rooms
    from server.database.APIKeys import APIKeys
    from server.database.RoomUsers import RoomUsers
    from server.database.MessageRecipientKeys import MessageRecipientKeys  # ключи расшифровки по получателям
    from server.database.MessageDeviceKeys import MessageDeviceKeys  # noqa: F401 — per-device wraps V3.2
    from server.database.MessageReads import MessageReads  # noqa: F401 — прочтение групповых сообщений по пользователю
    from server.database.MessageReactions import MessageReactions  # noqa: F401
    from server.database.Attachments import Attachments  # noqa: F401
    from server.database.MobileAppReleases import MobileAppReleases  # noqa: F401
    from server.database.OAuthAccounts import OAuthAccounts  # noqa: F401
    from server.database.UserKeyBackups import UserKeyBackups  # noqa: F401
    from server.database.Devices import Devices, DeviceOneTimePrekeys  # noqa: F401
    from server.database.DeviceLinkChallenges import DeviceLinkChallenges  # noqa: F401
    from server.database.DeviceLoginPending import DeviceLoginPending  # noqa: F401
    from server.database.EncryptedHistoryBlobs import EncryptedHistoryBlobs  # noqa: F401

    Base.metadata.create_all(bind=engine)
    apply_schema_patches()
