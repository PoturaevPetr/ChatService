"""
Redis presence: user_id → {node_id: connection_count} (мульти-девайс).
Позволяет одному пользователю иметь соединения на нескольких нодах одновременно.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from server.settings import settings

logger = logging.getLogger(__name__)


def _conn_key(user_id: uuid.UUID) -> str:
    return f"{settings.PRESENCE_KEY_PREFIX}{user_id}"


async def set_user_node(user_id: uuid.UUID, node_id: Optional[str] = None) -> bool:
    """Зарегистрировать/инкрементировать соединение пользователя на данной API-ноде."""
    from server.services.redis_client import get_redis

    nid = (node_id or settings.API_NODE_ID).strip()
    r = get_redis()
    if r is None:
        return False
    try:
        key = _conn_key(user_id)
        # HINCRBY: атомарный инкремент; если ключа нет — создаёт с 1
        await r.hincrby(key, nid, 1)
        await r.expire(key, settings.PRESENCE_CONN_TTL_SEC)
        return True
    except Exception as e:
        logger.warning("presence set failed: %s", e)
        return False


async def touch_user_node(user_id: uuid.UUID, node_id: Optional[str] = None) -> bool:
    """Продлить TTL (heartbeat / ping). Не меняет счётчик."""
    from server.services.redis_client import get_redis

    nid = (node_id or settings.API_NODE_ID).strip()
    r = get_redis()
    if r is None:
        return False
    try:
        key = _conn_key(user_id)
        # Ensure field exists (idempotent for heartbeat)
        cur = await r.hget(key, nid)
        if not cur:
            await r.hset(key, nid, "1")
        await r.expire(key, settings.PRESENCE_CONN_TTL_SEC)
        return True
    except Exception as e:
        logger.warning("presence touch failed: %s", e)
        return False


async def clear_user_node(user_id: uuid.UUID, only_if_node: Optional[str] = None) -> bool:
    """
    Декрементировать счётчик соединений на ноде. Удалить поле, если счётчик <= 0.
    Удалить весь ключ, если не осталось ни одной ноды.
    """
    from server.services.redis_client import get_redis

    r = get_redis()
    if r is None:
        return False
    key = _conn_key(user_id)
    nid = (only_if_node or settings.API_NODE_ID).strip()
    try:
        new_val = await r.hincrby(key, nid, -1)
        if new_val <= 0:
            await r.hdel(key, nid)
        # Если hash пустой — удаляем весь ключ
        remaining = await r.hlen(key)
        if remaining == 0:
            await r.delete(key)
        return True
    except Exception as e:
        logger.warning("presence clear failed: %s", e)
        return False


async def get_user_node(user_id: uuid.UUID) -> Optional[str]:
    """Получить одну (любую) ноду, на которой пользователь онлайн."""
    from server.services.redis_client import get_redis

    r = get_redis()
    if r is None:
        return None
    try:
        all_nodes = await r.hgetall(_conn_key(user_id))
        if not all_nodes:
            return None
        # Вернуть первую ноду с положительным счётчиком
        for nid, count in all_nodes.items():
            if int(count) > 0:
                return nid
        return None
    except Exception as e:
        logger.warning("presence get failed: %s", e)
        return None


async def get_all_user_nodes(user_id: uuid.UUID) -> List[str]:
    """Получить все ноды, на которых пользователь онлайн (для fan-out)."""
    from server.services.redis_client import get_redis

    r = get_redis()
    if r is None:
        return []
    try:
        all_nodes = await r.hgetall(_conn_key(user_id))
        if not all_nodes:
            return []
        return [nid for nid, count in all_nodes.items() if int(count) > 0]
    except Exception as e:
        logger.warning("presence get_all failed: %s", e)
        return []

