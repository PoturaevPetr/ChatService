import os
import secrets
from urllib.parse import ParseResult, urlparse, urlunparse


class Settings():
    @staticmethod
    def _normalize_redis_url(raw_url: str) -> str:
        """
        Нормализует REDIS_URL и исправляет частые ошибки конфигурации:
        - отсутствие схемы (redis://)
        - отсутствие DB в path (добавляет /0)
        - опечатка вида 6379:6379 (host=port) -> redis://redis:6379/0
        """
        candidate = (raw_url or "").strip()
        if not candidate:
            return "redis://redis:6379/0"

        if "://" not in candidate:
            candidate = f"redis://{candidate}"

        parsed = urlparse(candidate)
        host = parsed.hostname
        port = parsed.port

        # Частая опечатка: REDIS_URL=6379:6379
        # В таком случае hostname становится "6379", что не является валидным хостом Redis в docker-compose.
        if host and host.isdigit():
            host = os.getenv("REDIS_HOST", "redis").strip() or "redis"
            port = int(os.getenv("REDIS_PORT_INNER", "6379"))

        if not host:
            host = os.getenv("REDIS_HOST", "redis").strip() or "redis"

        if not port:
            port = int(os.getenv("REDIS_PORT_INNER", "6379"))

        username = parsed.username or ""
        password = parsed.password or ""
        auth = ""
        if username and password:
            auth = f"{username}:{password}@"
        elif password:
            auth = f":{password}@"
        elif username:
            auth = f"{username}@"

        netloc = f"{auth}{host}:{port}"
        path = parsed.path if parsed.path not in ("", "/") else "/0"

        return urlunparse(
            ParseResult(
                scheme=parsed.scheme or "redis",
                netloc=netloc,
                path=path,
                params="",
                query="",
                fragment="",
            )
        )

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

    # Redis (очередь доставки сообщений для воркера)
    REDIS_URL = _normalize_redis_url.__func__(os.getenv("REDIS_URL", "redis://redis:6379/0"))

    # Воркер доставки (отдельный процесс)
    WORKER_PORT = int(os.getenv("WORKER_PORT", "8321"))
    # URL API для вызовов из воркера (доставка через API)
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8320")
    # Секрет для внутреннего endpoint доставки (воркер -> API)
    INTERNAL_DELIVERY_SECRET = os.getenv("INTERNAL_DELIVERY_SECRET", "")

    # Speech Analytics (audio.pirogov.ai): загрузка с callback на этот сервис
    SPEECH_ANALYTICS_BASE_URL = os.getenv(
        "SPEECH_ANALYTICS_BASE_URL", "https://audio.pirogov.ai/api/v1"
    ).rstrip("/")
    SPEECH_ANALYTICS_API_KEY = os.getenv("SPEECH_ANALYTICS_API_KEY", "").strip()
    # Публичный базовый URL Chat API (как его видит сервис распознавания), без завершающего /
    TRANSCRIBE_CALLBACK_PUBLIC_URL = os.getenv("TRANSCRIBE_CALLBACK_PUBLIC_URL", "").rstrip("/")
    TRANSCRIBE_WEBHOOK_SECRET = os.getenv("TRANSCRIBE_WEBHOOK_SECRET", "").strip()

    # Novu (push): секрет из Dashboard → Settings → API Keys (Production).
    # Для EU: https://eu.api.novu.co
    NOVU_API_URL = os.getenv("NOVU_API_URL", "https://api.novu.co").rstrip("/")
    NOVU_SECRET_KEY = os.getenv("NOVU_SECRET_KEY", "").strip()
    # Идентификатор триггера workflow (поле name в POST /v1/events/trigger).
    NOVU_PUSH_TRIGGER_IDENTIFIER = os.getenv("NOVU_PUSH_TRIGGER_IDENTIFIER", "").strip()
    # Несколько FCM в Novu: identifier интеграции Kindred (в UI интеграции). Уходит в PATCH credentials
    # и в overrides.push.integrationIdentifier при trigger — выбор провайдера на бэкенде.
    NOVU_FCM_INTEGRATION_IDENTIFIER = os.getenv("NOVU_FCM_INTEGRATION_IDENTIFIER", "").strip()
    # Имя приложения в payload Novu (appName).
    NOVU_PUSH_APP_NAME = os.getenv("NOVU_PUSH_APP_NAME", "Kindred").strip() or "Kindred"

    # Внешний callback для mobileApp (доставка пушей во внешнем сервисе).
    MOBILE_APP_PUSH_CALLBACK_URL = os.getenv("MOBILE_APP_PUSH_CALLBACK_URL", "").strip()

    # Mobile app updates
    MOBILE_UPDATE_ADMIN_SECRET = os.getenv("MOBILE_UPDATE_ADMIN_SECRET", "").strip()
    MOBILE_RELEASES_STORAGE_DIR = os.getenv("MOBILE_RELEASES_STORAGE_DIR", "uploads/mobile-releases").strip()
    # Относительный путь (от корня ChatService) к HTML-шаблонам FastAPI.
    MOBILE_TEMPLATES_DIR_REL = os.getenv("MOBILE_TEMPLATES_DIR_REL", "server/templates").strip()
    # Публичный base URL ChatService для ссылок на загрузку релизов (например, https://chat.pirogov.ai).
    MOBILE_PUBLIC_BASE_URL = os.getenv("MOBILE_PUBLIC_BASE_URL", "").strip().rstrip("/")

    # MeetService: URL отдаётся клиенту в GET /api/v1/client/meet-service (без пересборки приложения).
    MEET_SERVICE_PUBLIC_URL = os.getenv("MEET_SERVICE_PUBLIC_URL", "").strip()

    # Ollama / LLM (AI-помощник): серверный ключ, выдача клиенту — через API (encrypted).
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://llm.oclinica.ru").strip().rstrip("/")
    OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "").strip()
    OLLAMA_API_KEY_HEADER = os.getenv("OLLAMA_API_KEY_HEADER", "").strip()
    LLM_ADMIN_SECRET = os.getenv("LLM_ADMIN_SECRET", "").strip()

    # Delivery: RabbitMQ durable queue + Redis presence/routing (единственный режим)
    RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/").strip()
    RABBIT_EXCHANGE = os.getenv("RABBIT_EXCHANGE", "chat.messages").strip() or "chat.messages"
    RABBIT_DELIVER_QUEUE = os.getenv("RABBIT_DELIVER_QUEUE", "chat.message.deliver").strip() or "chat.message.deliver"
    RABBIT_DELIVER_ROUTING_KEY = os.getenv("RABBIT_DELIVER_ROUTING_KEY", "message.deliver").strip() or "message.deliver"
    RABBIT_DLX = os.getenv("RABBIT_DLX", "chat.messages.dlx").strip() or "chat.messages.dlx"
    RABBIT_DLQ = os.getenv("RABBIT_DLQ", "chat.message.deliver.dlq").strip() or "chat.message.deliver.dlq"
    # Идентификатор процесса API (для Redis presence и канала ws:deliver:{node_id})
    API_NODE_ID = (os.getenv("API_NODE_ID") or os.getenv("HOSTNAME") or secrets.token_hex(8)).strip()
    PRESENCE_CONN_TTL_SEC = int(os.getenv("PRESENCE_CONN_TTL_SEC", "120"))
    PRESENCE_KEY_PREFIX = os.getenv("PRESENCE_KEY_PREFIX", "presence:conn:").strip() or "presence:conn:"
    WS_DELIVER_CHANNEL_PREFIX = os.getenv("WS_DELIVER_CHANNEL_PREFIX", "ws:deliver:").strip() or "ws:deliver:"

    # OAuth2 (Google, Яндекс, VK). Редирект: {origin}/auth/oauth/callback — origin должен быть в списке.
    OAUTH_GOOGLE_CLIENT_ID = os.getenv("OAUTH_GOOGLE_CLIENT_ID", "").strip()
    OAUTH_GOOGLE_CLIENT_SECRET = os.getenv("OAUTH_GOOGLE_CLIENT_SECRET", "").strip()
    OAUTH_YANDEX_CLIENT_ID = os.getenv("OAUTH_YANDEX_CLIENT_ID", "").strip()
    OAUTH_YANDEX_CLIENT_SECRET = os.getenv("OAUTH_YANDEX_CLIENT_SECRET", "").strip()
    OAUTH_VK_APP_ID = os.getenv("OAUTH_VK_APP_ID", os.getenv("OAUTH_VK_CLIENT_ID", "")).strip()
    OAUTH_VK_SECURE_KEY = os.getenv("OAUTH_VK_SECURE_KEY", os.getenv("OAUTH_VK_CLIENT_SECRET", "")).strip()
    # По умолчанию: Next на :3000 и типичный WebView/Capacitor без порта (http://localhost).
    OAUTH_FRONTEND_ORIGINS = [
        o.strip().rstrip("/")
        for o in os.getenv(
            "OAUTH_FRONTEND_ORIGINS",
            "http://localhost,http://localhost:3000",
        ).split(",")
        if o.strip()
    ]
    # Доп. redirect_uri (полные URL), например нестандартные схемы — по желанию.
    OAUTH_CUSTOM_REDIRECT_URIS = [
        u.strip() for u in os.getenv("OAUTH_CUSTOM_REDIRECT_URIS", "").split(",") if u.strip()
    ]
    # Публичный HTTPS URL моста …/auth/oauth/native-bridge (для Google/Яндекс). Если пусто — из MOBILE_PUBLIC_BASE_URL или API_BASE_URL.
    OAUTH_NATIVE_CALLBACK_URL = os.getenv("OAUTH_NATIVE_CALLBACK_URL", "").strip()
    # Схема для второго шага моста: com.kindred.messapp://auth/oauth/callback?code=…
    OAUTH_APP_RETURN_SCHEME = (os.getenv("OAUTH_APP_RETURN_SCHEME", "com.kindred.messapp").strip() or "com.kindred.messapp")


settings = Settings()