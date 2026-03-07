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
        """Установка нового WebSocket соединения"""
        await websocket.accept()

        # Добавляем соединение к пользователю
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

        # Сохраняем обратное отображение
        self.connection_to_user[websocket] = user_id

        logger.info(f"User {user_id} connected. Total connections: {len(self.active_connections)}")

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
            # Отправляем по всем активным соединениям пользователя
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error sending to user {user_id}: {e}")
                    # Удаляем неработающее соединение
                    await self.disconnect(connection)

    async def broadcast_to_room(self, room_id: uuid.UUID, message: dict, exclude_user: Optional[uuid.UUID] = None):
        """
        Отправка сообщения в комнату всем участникам

        Args:
            room_id: UUID комнаты
            message: Данные для отправки
            exclude_user: Исключить пользователя из рассылки
        """
        if room_id in self.room_connections:
            for user_id in self.room_connections[room_id]:
                if exclude_user and user_id == exclude_user:
                    continue
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
        logger.info(f"User {user_id} joined room {room_id}")

    def leave_room(self, user_id: uuid.UUID, room_id: uuid.UUID):
        """Выход пользователя из комнаты"""
        if room_id in self.room_connections:
            self.room_connections[room_id].discard(user_id)
            if not self.room_connections[room_id]:
                del self.room_connections[room_id]
            logger.info(f"User {user_id} left room {room_id}")

    def is_user_online(self, user_id: uuid.UUID) -> bool:
        """Проверка, онлайн ли пользователь"""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

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
