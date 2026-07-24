"""Общий async Redis-клиент (presence, pub/sub)."""
import logging

from server.settings import settings

logger = logging.getLogger(__name__)

_redis = None


def get_redis():
    """Ленивое подключение к Redis."""
    global _redis
    if _redis is None:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception as e:
            logger.warning("Redis not available: %s", e)
    return _redis


async def close_redis():
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None
