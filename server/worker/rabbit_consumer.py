"""RabbitMQ consumer: queue → Redis ws:deliver:{node_id} (без HTTP на API)."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from server.settings import settings
from server.services.presence import get_user_node
from server.services.delivery_broadcast import publish_deliver
from server.services.rabbit_delivery import get_rabbit_channel

logger = logging.getLogger(__name__)


async def _process_payload(payload: dict) -> None:
    message_id_str = payload.get("message_id")
    recipient_id_str = payload.get("recipient_id")
    sender_id_str = payload.get("sender_id")
    room_id_str = payload.get("room_id")
    encrypted_data = payload.get("encrypted_data")
    sent_at = payload.get("sent_at")
    if not message_id_str or not recipient_id_str:
        logger.warning("Invalid delivery payload: missing message_id or recipient_id")
        return

    notification = {
        "type": "new_message",
        "data": {
            "message_id": message_id_str,
            "sender_id": sender_id_str,
            "recipient_id": recipient_id_str,
            "room_id": room_id_str,
            "encrypted_data": encrypted_data,
            "sent_at": sent_at,
        },
    }
    body = {
        "recipient_id": recipient_id_str,
        "sender_id": sender_id_str or "",
        "room_id": room_id_str,
        "notification": notification,
    }

    recipient_id = uuid.UUID(recipient_id_str)
    node_id = await get_user_node(recipient_id)
    if node_id:
        ok = await publish_deliver(body, node_id=node_id)
        print(
            f"[Worker v2] Redis deliver node={node_id} message_id={message_id_str[:8]}... "
            f"recipient={recipient_id_str[:8]}... ok={ok}"
        )
    else:
        print(
            f"[Worker v2] recipient offline (no presence) message_id={message_id_str[:8]}... "
            f"recipient={recipient_id_str[:8]}..."
        )

    from server.database import SessionLocal
    from server.services.message_service import message_service

    db = SessionLocal()
    try:
        message_service.mark_as_delivered(uuid.UUID(message_id_str), db)
    except Exception as e:
        logger.exception("Failed to mark message %s as delivered: %s", message_id_str, e)
    finally:
        db.close()


async def run_rabbit_delivery_consumer():
    """Consume chat.message.deliver and route via Redis node channel."""
    try:
        import aio_pika
    except ImportError:
        logger.warning("aio-pika not installed, rabbit consumer disabled")
        return

    while True:
        try:
            channel = await get_rabbit_channel()
            if channel is None:
                logger.warning("RabbitMQ unavailable, retry in 5s")
                await asyncio.sleep(5)
                continue

            queue = await channel.declare_queue(
                settings.RABBIT_DELIVER_QUEUE,
                durable=True,
                arguments={"x-dead-letter-exchange": settings.RABBIT_DLX},
            )
            print(f"[Worker v2] Consuming queue={settings.RABBIT_DELIVER_QUEUE}")

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    try:
                        async with message.process(requeue=False):
                            payload = json.loads(message.body.decode("utf-8"))
                            await _process_payload(payload)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.exception("Rabbit message handle error: %s", e)
                        # requeue=False → DLQ при настроенном x-dead-letter-exchange
                        continue
        except asyncio.CancelledError:
            logger.info("Rabbit delivery consumer cancelled")
            break
        except Exception as e:
            logger.exception("Rabbit consumer loop error: %s", e)
            await asyncio.sleep(5)
