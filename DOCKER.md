# Запуск ChatService через Docker

## 🐳 Быстрый старт

### 1. Запуск с PostgreSQL

```bash
# Сборка и запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f api

# Остановка
docker-compose down
```

**Важно:** При первом запуске PostgreSQL автоматически создаст базу `ChatDatabase` и применит скрипт `init-db.sql`. API контейнер дождется готовности БД перед запуском.

Сервисы будут доступны на:
- **API**: http://localhost:8080 (в контейнере API слушает порт 8320; для воркера задайте `PORT=8320` в .env)
- **Worker**: http://localhost:8321/health
- **Redis**: localhost:6380 (по умолчанию)
- **RabbitMQ**: amqp localhost:5672, management http://localhost:15672
- **PostgreSQL**: localhost:5434
- **API Docs**: http://localhost:8080/docs

### Доставка сообщений

API → RabbitMQ → Worker → Redis `ws:deliver:{node_id}` → WebSocket на API-ноде.  
Воркер **не** вызывает HTTP `/api/internal/deliver` (маршрут удалён).

Подробнее: [docs/REALTIME_DELIVERY.md](docs/REALTIME_DELIVERY.md).

### Novu (push) — self-host рядом

Отдельный compose: [deploy/novu/README.md](deploy/novu/README.md).

```bash
docker network create kindred   # один раз
cd deploy/novu && cp .env.example .env   # секреты!
docker compose --env-file .env up -d
```

В корневом `.env` ChatService:

```bash
NOVU_API_URL=http://novu-api:3000
NOVU_SECRET_KEY=...   # тот же, что в deploy/novu/.env (или API key из dashboard)
NOVU_PUSH_TRIGGER_IDENTIFIER=...
```

API ChatService должен быть в сети `kindred` (уже в `docker-compose.yml`).

### 2. Только сборка образа

```bash
# Сборка
docker build -t chatservice:latest .

# Запуск с локальной БД
docker run -p 8080:8080 \
  -e DATABASE_URL=sqlite:///./chat_service.db \
  chatservice:latest
```

## 🔧 Переменные окружения

### Database
- `DB_HOST` - хост БД (по умолчанию: postgres)
- `DB_PORT` - порт БД (по умолчанию: 5432)
- `DB_USER` - пользователь БД (по умолчанию: postgres)
- `DB_PASSWORD` - пароль БД (по умолчанию: postgres)
- `DB_NAME` - имя БД (по умолчанию: ChatDatabase)

### Server
- `PORT` - порт приложения (по умолчанию: 8080)
- `DEBUG` - режим отладки (по умолчанию: true)

### JWT
- `JWT_SECRET_KEY` - секретный ключ для JWT
- `ACCESS_TOKEN_EXPIRE_MINUTES` - время жизни access токена (по умолчанию: 30)
- `REFRESH_TOKEN_EXPIRE_DAYS` - время жизни refresh токена (по умолчанию: 7)

### CORS
- `CORS_ORIGINS` - разрешенные origins для CORS (по умолчанию: *)

### Redis и воркер
- `REDIS_URL` - URL Redis для очереди доставки (по умолчанию: redis://localhost:6379/0)
- `WORKER_PORT` - порт воркера доставки (по умолчанию: 8321)
- `API_BASE_URL` - URL API для вызовов из воркера (в Docker: http://api:8320)
- `INTERNAL_DELIVERY_SECRET` - секрет для внутреннего endpoint доставки (заголовок X-Internal-Secret); если задан, воркер обязан его передавать

## 📝 Команды Docker Compose

```bash
# Запуск в фоне
docker-compose up -d

# Просмотр логов (все сервисы или только api/worker)
docker-compose logs -f
docker-compose logs -f api
docker-compose logs -f worker

# Перезапуск
docker-compose restart

# Остановка с удалением контейнеров
docker-compose down

# Остановка с удалением volumes (данных БД)
docker-compose down -v

# Пересборка образа
docker-compose build --no-cache

# Выполнить команду в контейнере
docker-compose exec api python -c "print('Hello')"
```

## 🔍 Проверка работоспособности

```bash
# Health check
curl http://localhost:8080/health

# Регистрация пользователя
curl -X POST http://localhost:8080/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "test_user", "service_id": "service_a"}'
```

## 🐛 Troubleshooting

### Проблема: База данных недоступна

```bash
# Проверить статус контейнера postgres
docker-compose ps postgres

# Проверить логи
docker-compose logs postgres

# Перезапустить БД
docker-compose restart postgres
```

### Проблема: API не запускается

```bash
# Проверить логи API
docker-compose logs api

# Пересобрать образ
docker-compose build --no-cache api
```

### Очистка всех данных

```bash
# Остановить и удалить всё включая данные БД
docker-compose down -v

# Удалить образы
docker rmi weeknotes-chat-api:latest weeknotes-chat-worker:latest
```

## 🚀 Production запуск

Для production используйте отдельный `.env` файл:

```bash
# Создайте .env файл
cat > .env << EOF
DB_PASSWORD=your_secure_password
JWT_SECRET_KEY=your_production_secret_key
CORS_ORIGINS=https://your-domain.com
DEBUG=false
EOF

# Запустите с .env
docker-compose --env-file .env up -d
```
