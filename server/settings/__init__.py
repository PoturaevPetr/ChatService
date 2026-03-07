import os
import secrets


class Settings():
    # Server config
    PORT = int(os.getenv("PORT", 8080))
    DEBUG = os.getenv("DEBUG", "true") == "true"

    # Database config
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "ChatDatabase")

    # Сначала проверяем DATABASE_URL из переменной окружения
    DATABASE_URL = os.getenv("DATABASE_URL")

    # Если не задан, собираем из компонентов
    if not DATABASE_URL:
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    # Если все еще пустой, используем SQLite для локальной разработки
    if not DATABASE_URL:
        DATABASE_URL = "sqlite:///./chat_service.db"

    # JWT config
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(64))
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

    # Encryption config
    ENCRYPTION_KEY_ROTATION_DAYS = int(os.getenv("ENCRYPTION_KEY_ROTATION_DAYS", 365))

    # WebSocket config
    WS_HEARTBEAT_INTERVAL = int(os.getenv("WS_HEARTBEAT_INTERVAL", 30))
    WS_MESSAGE_QUEUE_SIZE = int(os.getenv("WS_MESSAGE_QUEUE_SIZE", 100))

    # Rate limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 60))

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


settings = Settings()