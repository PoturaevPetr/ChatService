"""
Redis presence: user_id → API node_id (где открыт WebSocket).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from server.settings import settings

logger = logging.getLogger(__name__)


def _conn_key(user_id: uuid.UUID) -> str:
    return f"{settings.PRESENCE_KEY_PREFIX}{user_id}"


async def set_user_node(user_id: uuid.UUID, node_id: Optional[str] = None) -> bool:
    """Зарегистрировать, что пользователь онлайн на данной API-ноде."""
    from server.services.redis_client import get_redis

    nid = (node_id or settings.API_NODE_ID).strip()
    r = get_redis()
    if r is None:
        return False
    try:
        await r.set(_conn_key(user_id), nid, ex=settings.PRESENCE_CONN_TTL_SEC)
        return True
    except Exception as e:
        logger.warning("presence set failed: %s", e)
        return False


async def touch_user_node(user_id: uuid.UUID, node_id: Optional[str] = None) -> bool:
    """Продлить TTL (heartbeat / ping)."""
    return await set_user_node(user_id, node_id)


async def clear_user_node(user_id: uuid.UUID, only_if_node: Optional[str] = None) -> bool:
    """
    Снять presence. Если only_if_node задан — удаляем только если значение совпадает
    (чтобы новый connect на другой ноде не стёрли старым disconnect).
    """
    from server.services.redis_client import get_redis

    r = get_redis()
    if r is None:
        return False
    key = _conn_key(user_id)
    try:
        if only_if_node:
            cur = await r.get(key)
            if cur != only_if_node:
                return False
        await r.delete(key)
        return True
    except Exception as e:
        logger.warning("presence clear failed: %s", e)
        return False


async def get_user_node(user_id: uuid.UUID) -> Optional[str]:
    from server.services.redis_client import get_redis

    r = get_redis()
    if r is None:
        return None
    try:
        val = await r.get(_conn_key(user_id))
        return val if val else None
    except Exception as e:
        logger.warning("presence get failed: %s", e)
        return None
