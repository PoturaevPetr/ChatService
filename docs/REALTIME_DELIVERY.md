# Realtime delivery (greenfield)

Единственный режим: **RabbitMQ → delivery worker → Redis `ws:deliver:{node_id}` → API WebSocket**.

```
API (persist message)
  → publish Rabbit (chat.message.deliver)
  → Worker consume
  → Redis presence: user → node_id
  → PUBLISH ws:deliver:{node_id}
  → API node subscriber → local WS manager
```

Fallback: если Rabbit недоступен, API шлёт напрямую в локальный WS manager.

## Env

```
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
API_NODE_ID=api-1
REDIS_URL=redis://redis:6379/0
```

## Проверка

1. Worker health `/health`, в логах `Mode: RabbitMQ → Redis node channel`.
2. API startup: RabbitMQ OK + Deliver subscriber started.
3. `POST /api/internal/deliver` — **нет** (404); meet-call-push остаётся на `/api/internal/meet-call-push`.
