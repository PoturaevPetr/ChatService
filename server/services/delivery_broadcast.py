"""
Доставка по Redis Pub/Sub: канал ws:deliver:{node_id} —
только нода, где сидит получатель (воркер публикует напрямую).
"""
import asyncio
import json
import logging
import uuid

from server.settings import settings
from server.websocket.manager import manager

logger = logging.getLogger(__name__)

_subscriber_task: asyncio.Task | None = None


def node_deliver_channel(node_id: str | None = None) -> str:
    nid = (node_id or settings.API_NODE_ID).strip()
    return f"{settings.WS_DELIVER_CHANNEL_PREFIX}{nid}"


async def _handle_deliver_payload(data: dict) -> None:
    recipient_id = uuid.UUID(data["recipient_id"]) if data.get("recipient_id") else None
    sender_id = uuid.UUID(data["sender_id"]) if data.get("sender_id") else None
    room_id = uuid.UUID(data["room_id"]) if data.get("room_id") else None
    notification = data.get("notification")
    if not notification:
        return
    msg_id = (notification.get("data") or {}).get("message_id", "?")[:8]
    if recipient_id:
        print(f"[API] Deliver (pub/sub): message_id={msg_id}... -> user={recipient_id}")
        await manager.send_to_user(recipient_id, notification)
    elif room_id:
        print(f"[API] Deliver (pub/sub): message_id={msg_id}... -> room={room_id} (broadcast)")
        await manager.broadcast_to_room(room_id, notification, exclude_user=sender_id)


async def run_deliver_subscriber():
    """Подписка на канал доставки ноды и вызов локального manager."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("redis not installed, delivery broadcast disabled")
        return

    channel = node_deliver_channel()

    while True:
        try:
            redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)
            logger.info("Subscribed to delivery channel %s (node=%s)", channel, settings.API_NODE_ID)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    await _handle_deliver_payload(data)
                except Exception as e:
                    logger.exception("Delivery broadcast handle error: %s", e)
        except asyncio.CancelledError:
            logger.info("Deliver subscriber cancelled")
            break
        except Exception as e:
            logger.exception("Deliver subscriber error: %s", e)
            await asyncio.sleep(5)


async def publish_deliver(payload: dict, node_id: str) -> bool:
    """Опубликовать задачу доставки в Redis канал ws:deliver:{node_id}."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return False
    channel = node_deliver_channel(node_id)
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.publish(channel, json.dumps(payload))
        await redis_client.close()
        return True
    except Exception as e:
        logger.warning("Publish deliver failed: %s", e)
        return False


def start_deliver_subscriber():
    global _subscriber_task
    if _subscriber_task is not None:
        return
    _subscriber_task = asyncio.create_task(run_deliver_subscriber())
    logger.info("Deliver subscriber task started (node=%s)", settings.API_NODE_ID)


def stop_deliver_subscriber():
    global _subscriber_task
    if _subscriber_task is not None:
        _subscriber_task.cancel()
        _subscriber_task = None
