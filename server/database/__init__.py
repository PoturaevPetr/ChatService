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
        "ALTER TABLE device_login_pending ADD COLUMN IF NOT EXISTS encrypted_master_key TEXT",
        "ALTER TABLE room_user ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN DEFAULT true",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_enabled BOOLEAN DEFAULT false",
        # V2/V3 legacy cleanup (safe when tables absent — IF EXISTS / IF NOT EXISTS)
        "ALTER TABLE users DROP COLUMN IF EXISTS keys_migrated_v2",
        "ALTER TABLE attachments DROP COLUMN IF EXISTS server_decrypt_key_b64",
        "ALTER TABLE attachments DROP COLUMN IF EXISTS server_decrypt_nonce_b64",
        "DROP TABLE IF EXISTS user_keys CASCADE",
        # Message device keys: allow separate keys per (message_id, user_id, device_id)
        "ALTER TABLE message_device_keys DROP CONSTRAINT IF EXISTS uq_message_device_keys_message_device",
        "ALTER TABLE message_device_keys DROP CONSTRAINT IF EXISTS uq_message_device_keys_user_device",
        "DELETE FROM message_device_keys a USING message_device_keys b WHERE a.id > b.id AND a.message_id = b.message_id AND a.user_id = b.user_id AND a.device_id = b.device_id",
        "ALTER TABLE message_device_keys ADD CONSTRAINT uq_message_device_keys_user_device UNIQUE (message_id, user_id, device_id)",
        # Cloud Drafts table
        """CREATE TABLE IF NOT EXISTS user_drafts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            index_date TIMESTAMPTZ DEFAULT NOW(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
            encrypted_data TEXT NOT NULL,
            nonce VARCHAR(64) NOT NULL,
            encrypted_aes_key TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_user_drafts_user_room UNIQUE (user_id, room_id)
        )""",
        "ALTER TABLE user_drafts ADD COLUMN IF NOT EXISTS index_date TIMESTAMPTZ DEFAULT NOW()",
        "CREATE INDEX IF NOT EXISTS ix_user_drafts_user_id ON user_drafts (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_drafts_room_id ON user_drafts (room_id)",
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
    from server.database.UserDrafts import UserDrafts  # noqa: F401

    Base.metadata.create_all(bind=engine)
    apply_schema_patches()

    try:
        from server.database.seed_test_users import seed_test_users
        with SessionLocal() as db:
            seed_test_users(db)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Seed test users warning: %s", exc)
