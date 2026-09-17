"""
Сервис синхронизации E2E-зашифрованных черновиков (Cloud Drafts).
Хранение: Redis (Hash drafts:{user_id}) + PostgreSQL (таблица user_drafts).
Рассылка: WebSocket-события draft_updated / draft_deleted другим сессиям пользователя.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from server.database.UserDrafts import UserDrafts
from server.services.redis_client import get_redis
from server.websocket.manager import manager

logger = logging.getLogger(__name__)

_drafts_schema_ensured = False


def _ensure_drafts_schema(db: Session) -> None:
    global _drafts_schema_ensured
    if _drafts_schema_ensured:
        return
    try:
        from sqlalchemy import text
        db.execute(text("ALTER TABLE user_drafts ADD COLUMN IF NOT EXISTS index_date TIMESTAMPTZ DEFAULT NOW()"))
        db.execute(text("ALTER TABLE user_drafts ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()"))
        db.commit()
        _drafts_schema_ensured = True
    except Exception as e:
        db.rollback()
        logger.warning("Failed to auto-patch user_drafts schema: %s", e)


class DraftService:
    @staticmethod
    def _redis_key(user_id: uuid.UUID) -> str:
        return f"drafts:{user_id}"

    @classmethod
    async def get_user_drafts(cls, user_id: uuid.UUID, db: Session) -> List[dict]:
        """
        Получить все сохраненные черновики пользователя.
        Сначала проверяет Redis, при отсутствии — подгружает из PostgreSQL и кэширует.
        """
        _ensure_drafts_schema(db)
        r = get_redis()
        rk = cls._redis_key(user_id)

        if r:
            try:
                cached = await r.hgetall(rk)
                if cached:
                    drafts = []
                    for raw in cached.values():
                        try:
                            drafts.append(json.loads(raw))
                        except Exception:
                            pass
                    drafts.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
                    return drafts
            except Exception as e:
                logger.warning("Redis error getting drafts for %s: %s", user_id, e)

        # Fallback to PostgreSQL
        rows = (
            db.query(UserDrafts)
            .filter(UserDrafts.user_id == user_id)
            .order_by(UserDrafts.updated_at.desc())
            .all()
        )
        drafts = []
        pipeline_data: Dict[str, str] = {}
        for row in rows:
            item = {
                "room_id": str(row.room_id),
                "encrypted_data": row.encrypted_data,
                "nonce": row.nonce,
                "encrypted_aes_key": row.encrypted_aes_key,
                "updated_at": row.updated_at.isoformat() if row.updated_at else datetime.now(timezone.utc).isoformat(),
            }
            drafts.append(item)
            pipeline_data[str(row.room_id)] = json.dumps(item)

        if r and pipeline_data:
            try:
                await r.hset(rk, mapping=pipeline_data)
            except Exception as e:
                logger.warning("Redis error repopulating drafts for %s: %s", user_id, e)

        return drafts

    @classmethod
    async def save_draft(
        cls,
        user_id: uuid.UUID,
        room_id: uuid.UUID,
        encrypted_data: str,
        nonce: str,
        encrypted_aes_key: str,
        db: Session,
    ) -> dict:
        """
        Сохранить или обновить черновик в БД и Redis, и оповестить другие устройства пользователя.
        """
        _ensure_drafts_schema(db)
        now = datetime.now(timezone.utc)
        row = (
            db.query(UserDrafts)
            .filter(UserDrafts.user_id == user_id, UserDrafts.room_id == room_id)
            .first()
        )
        if row:
            row.encrypted_data = encrypted_data
            row.nonce = nonce
            row.encrypted_aes_key = encrypted_aes_key
            row.updated_at = now
            row.index_date = now
        else:
            row = UserDrafts(
                user_id=user_id,
                room_id=room_id,
                encrypted_data=encrypted_data,
                nonce=nonce,
                encrypted_aes_key=encrypted_aes_key,
                created_at=now,
                updated_at=now,
                index_date=now,
            )
            db.add(row)

        db.commit()

        payload = {
            "room_id": str(room_id),
            "encrypted_data": encrypted_data,
            "nonce": nonce,
            "encrypted_aes_key": encrypted_aes_key,
            "updated_at": now.isoformat(),
        }

        # Update Redis
        r = get_redis()
        if r:
            try:
                await r.hset(cls._redis_key(user_id), str(room_id), json.dumps(payload))
            except Exception as e:
                logger.warning("Redis error saving draft for %s room %s: %s", user_id, room_id, e)

        # Notify other connections of this user
        try:
            await manager.send_to_user(
                user_id,
                {
                    "type": "draft_updated",
                    "data": payload,
                },
            )
        except Exception as e:
            logger.warning("Failed to broadcast draft_updated to user %s: %s", user_id, e)

        return payload

    @classmethod
    async def delete_draft(
        cls,
        user_id: uuid.UUID,
        room_id: uuid.UUID,
        db: Session,
    ) -> bool:
        """
        Удалить черновик из БД и Redis, оповестить другие устройства пользователя.
        """
        _ensure_drafts_schema(db)
        db.query(UserDrafts).filter(
            UserDrafts.user_id == user_id, UserDrafts.room_id == room_id
        ).delete()
        db.commit()

        r = get_redis()
        if r:
            try:
                await r.hdel(cls._redis_key(user_id), str(room_id))
            except Exception as e:
                logger.warning("Redis error deleting draft for %s room %s: %s", user_id, room_id, e)

        try:
            await manager.send_to_user(
                user_id,
                {
                    "type": "draft_deleted",
                    "data": {"room_id": str(room_id)},
                },
            )
        except Exception as e:
            logger.warning("Failed to broadcast draft_deleted to user %s: %s", user_id, e)

        return True


draft_service = DraftService()
