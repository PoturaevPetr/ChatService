from typing import Dict, List, Optional, Set
from fastapi import WebSocket
from datetime import datetime
import uuid
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Менеджер WebSocket подключений для отслеживания активных соединений
    и доставки сообщений пользователям
    """

    def __init__(self):
        # Активные соединения: user_id -> list of WebSocket connections
        self.active_connections: Dict[uuid.UUID, List[WebSocket]] = {}

        # Обратное отображение: websocket -> user_id
        self.connection_to_user: Dict[WebSocket, uuid.UUID] = {}

        # Подключения к комнатам: room_id -> set of user_ids
        self.room_connections: Dict[uuid.UUID, Set[uuid.UUID]] = {}

    async def connect(self, websocket: WebSocket, user_id: uuid.UUID):
        """Установка нового WebSocket соединения. Старые соединения этого пользователя закрываются (один сокет на пользователя)."""
        if user_id in self.active_connections:
            old_connections = list(self.active_connections[user_id])
            for room_id in list(self.room_connections.keys()):
                self.room_connections[room_id].discard(user_id)
                if not self.room_connections[room_id]:
                    del self.room_connections[room_id]
            del self.active_connections[user_id]
            for old_ws in old_connections:
                if old_ws in self.connection_to_user:
                    del self.connection_to_user[old_ws]
                try:
                    await old_ws.close(code=1000)
                except Exception as e:
                    logger.debug("Error closing old websocket for user %s: %s", user_id, e)
            logger.info("Closed %d old connection(s) for user %s (new connection incoming)", len(old_connections), user_id)
            print(f"[API] Закрыто {len(old_connections)} старых соединений user={user_id}")

        await websocket.accept()

        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        self.connection_to_user[websocket] = user_id

        logger.info(f"User {user_id} connected. Total connections: {len(self.connection_to_user)}")

    async def disconnect(self, websocket: WebSocket):
        """Отключение WebSocket соединения"""
        user_id = self.connection_to_user.get(websocket)
        if user_id:
            # Удаляем соединение из списка пользователя
            if user_id in self.active_connections:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                    logger.info(f"User {user_id} fully disconnected")

            # Удаляем обратное отображение
            del self.connection_to_user[websocket]

            # Удаляем из комнат
            for room_id in self.room_connections:
                if user_id in self.room_connections[room_id]:
                    self.room_connections[room_id].remove(user_id)

        logger.info(f"WebSocket disconnected. Remaining connections: {len(self.connection_to_user)}")

    async def send_to_user(self, user_id: uuid.UUID, message: dict):
        """
        Отправка сообщения конкретному пользователю по всем активным соединениям

        Args:
            user_id: UUID получателя
            message: Данные для отправки (dict)
        """
        if user_id in self.active_connections:
            msg_id = (message.get("data") or {}).get("message_id", "")
            msg_id_short = str(msg_id)[:8] if msg_id else "-"
            # Отправляем по всем активным соединениям пользователя
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                    if message.get("type") == "new_message":
                        print(f"[API] WebSocket: отправлено user={user_id} message_id={msg_id_short}...")
                except Exception as e:
                    logger.error(f"Error sending to user {user_id}: {e}")
                    # Удаляем неработающее соединение
                    await self.disconnect(connection)
        else:
            if message.get("type") == "new_message":
                print(f"[API] WebSocket: получатель {user_id} не подключён (new_message не доставлен)")

    async def broadcast_to_room(self, room_id: uuid.UUID, message: dict, exclude_user: Optional[uuid.UUID] = None):
        """
        Отправка сообщения в комнату всем участникам

        Args:
            room_id: UUID комнаты
            message: Данные для отправки
            exclude_user: Исключить пользователя из рассылки
        """
        print(room_id)
        print(message)
        print(exclude_user)
        if room_id not in self.room_connections:
            if message.get("type") == "new_message":
                print(f"[API] WebSocket: комната {room_id} пуста или не найдена (никто не в join_room)")
            return
        users_in_room = list(self.room_connections[room_id])
        to_send = [u for u in users_in_room if u != exclude_user]
        if message.get("type") == "new_message":
            print(f"[API] WebSocket: комната {room_id} — в комнате: {users_in_room}, исключён отправитель: {exclude_user}, отправить: {to_send}")
        if not to_send:
            print(f"[API] WebSocket: получатель не в комнате на этом воркере (доставка не выполнена)")
            return
        for user_id in to_send:
            await self.send_to_user(user_id, message)

    async def broadcast_to_all(self, message: dict):
        """Трансляция сообщения всем подключенным пользователям"""
        for user_id in self.active_connections:
            await self.send_to_user(user_id, message)

    def join_room(self, user_id: uuid.UUID, room_id: uuid.UUID):
        """Присоединение пользователя к комнате"""
        if room_id not in self.room_connections:
            self.room_connections[room_id] = set()
        self.room_connections[room_id].add(user_id)
        now_in_room = list(self.room_connections[room_id])
        logger.info(f"User {user_id} joined room {room_id}")
        print(f"[API] Комната {room_id}: сейчас в комнате {now_in_room}")

    def leave_room(self, user_id: uuid.UUID, room_id: uuid.UUID):
        """Выход пользователя из комнаты"""
        if room_id in self.room_connections:
            self.room_connections[room_id].discard(user_id)
            if not self.room_connections[room_id]:
                del self.room_connections[room_id]
                remaining = []
            else:
                remaining = list(self.room_connections[room_id])
            logger.info(f"User {user_id} left room {room_id}")
            print(f"[API] Комната {room_id}: после выхода user={user_id} остались {remaining}")

    def is_user_online(self, user_id: uuid.UUID) -> bool:
        """Проверка, онлайн ли пользователь"""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

    def is_user_in_room(self, user_id: uuid.UUID, room_id: uuid.UUID) -> bool:
        """Проверка, находится ли пользователь в join_room для комнаты."""
        return room_id in self.room_connections and user_id in self.room_connections[room_id]

    def get_online_users(self) -> List[uuid.UUID]:
        """Получить список всех онлайн пользователей"""
        return list(self.active_connections.keys())

    def get_online_count(self) -> int:
        """Получить количество онлайн пользователей"""
        return len(self.active_connections)

    def get_user_connection_count(self, user_id: uuid.UUID) -> int:
        """Получить количество активных соединений пользователя"""
        return len(self.active_connections.get(user_id, []))


# Глобальный экземпляр менеджера подключений
manager = ConnectionManager()
