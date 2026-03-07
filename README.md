# ChatService - Защищенный сервис обмена сообщениями

Сервис для обмена зашифрованными сообщениями с поддержкой кросс-доставки через REST и WebSocket.

## 🚀 Быстрый старт

### Через Docker (рекомендуется)

```bash
# Запуск с PostgreSQL
docker-compose up -d

# Просмотр логов
docker-compose logs -f api

# Остановка
docker-compose down
```

Подробнее в [DOCKER.md](DOCKER.md)

### Локально

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск сервера
python start.py
```

Сервис будет доступен по адресу: `http://localhost:8080`

Документация API: `http://localhost:8080/docs`

## 🔐 Особенности
- **JWT авторизация**: Secure token-based authentication
- **API ключи**: Для интеграции внешних сервисов
- **Real-time уведомления**: WebSocket для мгновенной доставки
- **Цифровая подпись**: Подтверждение авторства сообщений

## 🚀 Быстрый старт

### Установка зависимостей

```bash
pip install -r requirements.txt
```

### Запуск сервера

```bash
python start.py
```

Сервис будет доступен по адресу: `http://localhost:8080`

Документация API: `http://localhost:8080/docs`

## 📚 API Documentation

### 1. Регистрация пользователя

```bash
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "john_doe",
  "service_id": "service_a"
}
```

**Ответ:**

```json
{
  "user_id": "uuid",
  "username": "john_doe",
  "public_key": "-----BEGIN PUBLIC KEY-----...",
  "private_key": "-----BEGIN PRIVATE KEY-----...",  // Только при регистрации!
  "access_token": "eyJ...",
  "refresh_token": "eyJ..."
}
```

⚠️ **Важно:** Сохраните `private_key` - он больше не будет доступен!

### 2. Получить публичный ключ пользователя

```bash
GET /api/v1/keys/public/{user_id}
Authorization: Bearer {access_token}
```

### 3. Отправить зашифрованное сообщение

```bash
POST /api/v1/messages/
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "recipient_id": "uuid",
  "message": {
    "text": "Hello!",
    "timestamp": 1234567890
  },
  "sign_message": true
}
```

Сообщение будет:
1. Зашифровано публичным ключом получателя
2. Сохранено в БД
3. Доставлено по WebSocket если получатель онлайн

### 4. Получить сообщения (для polling клиентов)

```bash
GET /api/v1/messages/
Authorization: Bearer {access_token}

# Или только непрочитанные
GET /api/v1/messages/unread
Authorization: Bearer {access_token}
```

### 5. WebSocket подключение

```javascript
const ws = new WebSocket(`ws://localhost:8080/ws/${user_id}?token=${access_token}`);

ws.onopen = () => {
  console.log('WebSocket connected');
  // Присоединиться к комнате
  ws.send(JSON.stringify({
    type: 'join_room',
    data: { room_id: 'room-uuid' }
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Received:', data);

  // Типы сообщений:
  // - connected: Успешное подключение
  // - new_message: Новое сообщение
  // - message_read: Сообщение прочитано
  // - user_online: Пользователь онлайн
  // - user_offline: Пользователь оффлайн
  // - user_typing: Пользователь печатает
};

// Уведомление о наборе текста
function sendTypingIndicator(roomId, isTyping) {
  ws.send(JSON.stringify({
    type: 'typing',
    data: {
      room_id: roomId,
      is_typing: isTyping
    }
  }));
}
```

## 🔑 Структура шифрования

### Гибридное шифрование

```
1. Отправитель получает публичный ключ получателя
2. Генерирует случайный AES-256 ключ
3. Шифрует сообщение AES-GCM
4. Шифрует AES ключ RSA-4096 публичным ключом получателя
5. Отправляет зашифрованные данные + зашифрованный AES ключ
```

### Поток сообщения

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Service A │         │ ChatService  │         │   Service B │
│   (Sender)  │         │              │         │  (Recipient)│
└──────┬──────┘         └──────┬───────┘         └──────┬──────┘
       │                       │                        │
       │ 1. GET /keys/public/  │                        │
       │    recipient_id       │                        │
       │──────────────────────▶│                        │
       │                       │                        │
       │ 2. public_key         │                        │
       │◀──────────────────────│                        │
       │                       │                        │
       │ 3. Encrypt message    │                        │
       │    (AES + RSA)        │                        │
       │                       │                        │
       │ 4. POST /messages/    │                        │
       │──────────────────────▶│                        │
       │                       │                        │
       │                       │ 5. Save to DB          │
       │                       │                        │
       │                       │ 6. WebSocket notify    │
       │                       │───────────────────────▶│
       │                       │                        │
       │                       │                        │ 7. Decrypt & Display
```

## 🛡️ Безопасность

- **AES-256-GCM**: Для шифрования данных сообщений
- **RSA-4096**: Для шифрования AES ключей
- **JWT токены**: Для аутентификации
- **API ключи**: Хешируются SHA-256, никогда не хранятся в открытом виде
- **CORS**: Настраивается через переменные окружения

## 🔧 Переменные окружения

```bash
# Server
PORT=8080
DEBUG=true

# Database
DATABASE_URL=sqlite:///./chat_service.db

# JWT
JWT_SECRET_KEY=your-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=*
```

## 📁 Структура проекта

```
server/
├── auth/              # JWT и API ключи
├── crypto/            # Шифрование (AES + RSA)
├── database/          # Модели БД
├── websocket/         # WebSocket менеджер
├── services/          # Бизнес-логика
├── api/               # REST endpoints
└── settings/          # Конфигурация
```

## 🧪 Примеры использования

См. `examples/python_client.py` для полного примера клиента на Python.

## 📝 Лицензия

MIT License
