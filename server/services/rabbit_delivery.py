"""RabbitMQ: публикация задач доставки."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional
import uuid

from server.settings import settings

logger = logging.getLogger(__name__)

_connection = None
_channel = None
_topology_ready = False


async def _ensure_topology(channel) -> None:
    global _topology_ready
    if _topology_ready:
        return
    # DLX + DLQ
    dlx = await channel.declare_exchange(settings.RABBIT_DLX, type="fanout", durable=True)
    dlq = await channel.declare_queue(settings.RABBIT_DLQ, durable=True)
    await dlq.bind(dlx)

    exchange = await channel.declare_exchange(
        settings.RABBIT_EXCHANGE,
        type="topic",
        durable=True,
    )
    queue = await channel.declare_queue(
        settings.RABBIT_DELIVER_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.RABBIT_DLX,
        },
    )
    await queue.bind(exchange, routing_key=settings.RABBIT_DELIVER_ROUTING_KEY)
    _topology_ready = True
    logger.info(
        "RabbitMQ topology ready: exchange=%s queue=%s",
        settings.RABBIT_EXCHANGE,
        settings.RABBIT_DELIVER_QUEUE,
    )


async def get_rabbit_channel():
    """Ленивое подключение к RabbitMQ (aio-pika)."""
    global _connection, _channel
    try:
        import aio_pika
    except ImportError:
        logger.warning("aio-pika not installed")
        return None

    try:
        if _channel is not None and not _channel.is_closed:
            return _channel
        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        _channel = await _connection.channel()
        await _channel.set_qos(prefetch_count=32)
        await _ensure_topology(_channel)
        return _channel
    except Exception as e:
        logger.warning("RabbitMQ connect failed: %s", e)
        _connection = None
        _channel = None
        return None


async def publish_message_deliver(
    message_id: uuid.UUID,
    sender_id: uuid.UUID,
    recipient_id: Optional[uuid.UUID],
    room_id: Optional[uuid.UUID],
    encrypted_data: str,
    sent_at: datetime,
    target_user_id: Optional[uuid.UUID] = None,
) -> bool:
    """Положить задачу доставки в RabbitMQ. True если опубликовано."""
    try:
        import aio_pika
    except ImportError:
        return False

    channel = await get_rabbit_channel()
    if channel is None:
        return False

    dest_user_id = target_user_id or recipient_id
    payload = {
        "message_id": str(message_id),
        "sender_id": str(sender_id),
        "recipient_id": str(recipient_id) if recipient_id else None,
        "room_id": str(room_id) if room_id else None,
        "encrypted_data": encrypted_data,
        "sent_at": sent_at.isoformat(),
        "target_user_id": str(dest_user_id) if dest_user_id else None,
    }
    try:
        exchange = await channel.declare_exchange(
            settings.RABBIT_EXCHANGE,
            type="topic",
            durable=True,
        )
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json",
            ),
            routing_key=settings.RABBIT_DELIVER_ROUTING_KEY,
        )
        logger.debug("Published deliver task message_id=%s target_user=%s", message_id, dest_user_id)
        return True
    except Exception as e:
        logger.error("Rabbit publish failed: %s", e)
        return False


async def close_rabbit():
    global _connection, _channel, _topology_ready
    try:
        if _channel is not None and not _channel.is_closed:
            await _channel.close()
    except Exception:
        pass
    try:
        if _connection is not None and not _connection.is_closed:
            await _connection.close()
    except Exception:
        pass
    _channel = None
    _connection = None
    _topology_ready = False


async def ping_rabbit() -> bool:
    ch = await get_rabbit_channel()
    return ch is not None
