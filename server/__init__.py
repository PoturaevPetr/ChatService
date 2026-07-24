from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from server.settings import settings

# Импорт роутеров (после создания app)
from server.api import auth, keys, messages, websocket, users, rooms, internal, attachments, transcription, push, mobile_updates, client_config, devices, history, llm


app = FastAPI(
    title="ChatService API",
    description="Secure encrypted messaging service with cross-delivery (REST + WebSocket)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Корневые endpoints
@app.get("/")
async def root():
    return {"message": "ChatService API is running", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/admin/releases", include_in_schema=False)
async def legacy_mobile_updates_admin_page():
    return RedirectResponse(url="/api/v1/mobile/admin/releases", status_code=307)


@app.get("/admin/releases/script.js", include_in_schema=False)
async def legacy_mobile_updates_admin_script():
    return RedirectResponse(url="/api/v1/mobile/admin/releases/script.js", status_code=307)


@app.post("/admin/releases/upload", include_in_schema=False)
async def legacy_mobile_updates_admin_upload():
    return RedirectResponse(url="/api/v1/mobile/admin/releases/upload", status_code=307)

# Подключаем роутеры
app.include_router(auth.router)
app.include_router(client_config.router)
app.include_router(keys.router)
app.include_router(devices.router)
app.include_router(history.router)
app.include_router(messages.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(websocket.router)
app.include_router(internal.router)
app.include_router(attachments.router)
app.include_router(transcription.router)
app.include_router(push.router)
app.include_router(mobile_updates.router)
app.include_router(llm.router)


@app.get("/admin/llm", include_in_schema=False)
async def legacy_llm_admin_page():
    return RedirectResponse(url="/api/v1/llm/admin", status_code=307)

@app.on_event("startup")
async def startup_event():
    """Действия при запуске сервера"""
    import time
    from server.database import init_db, engine
    import sqlalchemy

    print("🚀 ChatService API starting...")
    print(f"📡 CORS origins: {settings.CORS_ORIGINS}")
    print(f"🔐 Encryption: AES-256-GCM + RSA-4096")
    print(f"🌐 WebSocket endpoint: /ws/{{user_id}}?token=<jwt>")
    print(f"💾 Database: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL}")
    print(f"📮 Redis: {settings.REDIS_URL.split('@')[-1] if '@' in settings.REDIS_URL else settings.REDIS_URL}")
    print(f"🧩 API_NODE_ID: {settings.API_NODE_ID}")
    print(f"🐇 RabbitMQ: {settings.RABBITMQ_URL.split('@')[-1] if '@' in settings.RABBITMQ_URL else settings.RABBITMQ_URL}")

    # Ждем готовности базы данных (для Docker)
    if "postgresql" in settings.DATABASE_URL:
        print("⏳ Waiting for PostgreSQL to be ready...")
        max_retries = 30
        for i in range(max_retries):
            try:
                with engine.connect() as conn:
                    conn.execute(sqlalchemy.text("SELECT 1"))
                print("✅ PostgreSQL is ready!")
                break
            except Exception as e:
                if i < max_retries - 1:
                    print(f"⏳ PostgreSQL not ready yet, retrying... ({i+1}/{max_retries})")
                    time.sleep(2)
                else:
                    print(f"❌ Failed to connect to PostgreSQL: {e}")
                    raise

    # Инициализируем базу данных
    init_db()
    print("✅ Database tables created successfully")

    # Проверка Redis (presence + deliver pub/sub)
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await r.ping()
        await r.close()
        print("✅ Redis: OK (presence + deliver pub/sub)")
    except Exception as e:
        print(f"❌ Redis: unreachable — {e}")

    # Подписка на Redis Pub/Sub для доставки на эту ноду
    try:
        from server.services.delivery_broadcast import start_deliver_subscriber
        start_deliver_subscriber()
        print("✅ Deliver subscriber (Redis Pub/Sub) started")
    except Exception as e:
        print(f"⚠️ Deliver subscriber not started: {e}")

    try:
        from server.services.rabbit_delivery import ping_rabbit

        if await ping_rabbit():
            print("✅ RabbitMQ: OK (publish deliver)")
        else:
            print("❌ RabbitMQ: unreachable — publish will fallback to local WS")
    except Exception as e:
        print(f"❌ RabbitMQ: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке сервера"""
    print("🛑 ChatService shutting down...")
    try:
        from server.services.delivery_broadcast import stop_deliver_subscriber
        stop_deliver_subscriber()
    except Exception:
        pass
    try:
        from server.services.rabbit_delivery import close_rabbit
        await close_rabbit()
    except Exception:
        pass




