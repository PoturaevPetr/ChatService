from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from server.settings import settings

# Импорт роутеров (после создания app)
from server.api import auth, keys, messages, websocket, users, rooms


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

# Подключаем роутеры
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(messages.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(websocket.router)


@app.on_event("startup")
async def startup_event():
    """Действия при запуске сервера"""
    import time
    from server.database import init_db, engine
    import sqlalchemy

    print("🚀 ChatService starting...")
    print(f"📡 CORS origins: {settings.CORS_ORIGINS}")
    print(f"🔐 Encryption: AES-256-GCM + RSA-4096")
    print(f"🌐 WebSocket endpoint: /ws/{{user_id}}?token=<jwt>")
    print(f"💾 Database URL: {settings.DATABASE_URL}")

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


@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке сервера"""
    print("🛑 ChatService shutting down...")




