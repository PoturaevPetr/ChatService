"""
Воркер доставки: RabbitMQ → Redis ws:deliver:{node} (без HTTP на API).
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.settings import settings

logger = logging.getLogger(__name__)

_consumer_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task

    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.ping()
        await redis_client.close()
        print("✅ [Worker] Redis: OK")
    except Exception as e:
        print(f"❌ [Worker] Redis: unreachable — {e}")

    from server.services.rabbit_delivery import ping_rabbit, close_rabbit
    from server.worker.rabbit_consumer import run_rabbit_delivery_consumer

    ok = await ping_rabbit()
    if ok:
        print(f"✅ [Worker] RabbitMQ: OK ({settings.RABBITMQ_URL.split('@')[-1]})")
    else:
        print(f"❌ [Worker] RabbitMQ: unreachable — {settings.RABBITMQ_URL}")
    print("📮 [Worker] Mode: RabbitMQ → Redis node channel")
    _consumer_task = asyncio.create_task(run_rabbit_delivery_consumer())

    logger.info("Delivery consumer started")
    yield
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    try:
        await close_rabbit()
    except Exception:
        pass


app = FastAPI(
    title="ChatService Delivery Worker",
    description="Доставка new_message: RabbitMQ → Redis ws:deliver:{node}",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "delivery-worker",
    }
