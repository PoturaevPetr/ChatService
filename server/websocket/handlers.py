from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect, status
from datetime import datetime
import uuid
import json
import logging

from server.websocket.manager import manager
from server.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """Обработчик WebSocket соединений"""

    def __init__(self, websocket: WebSocket, user_id: uuid.UUID, token: str):
        self.websocket = websocket
        self.user_id = user_id
        self.token = token

    async def connect(self):
        """Установка соединения"""
        await manager.connect(self.websocket, self.user_id)
        await NotificationService.notify_user_online(self.user_id)

        # Отправляем приветственное сообщение
        await self.websocket.send_json({
            "type": "connected",
            "data": {
                "user_id": str(self.user_id),
                "timestamp": datetime.utcnow().isoformat(),
                "message": "WebSocket connection established"
            }
        })

    async def disconnect(self):
        """Закрытие соединения"""
        try:
            await NotificationService.notify_user_offline(self.user_id)
            await manager.disconnect(self.websocket)
        except Exception as e:
            logger.debug(f"Error during disconnect: {e}")

    async def handle_message(self, message: dict):
        """
        Обработка входящего сообщения от клиента

        Args:
            message: Данные сообщения от клиента
        """
        try:
            message_type = message.get("type")
            data = message.get("data", {})

            if message_type == "ping":
                await self._handle_ping()

            elif message_type == "join_room":
                await self._handle_join_room(data)

            elif message_type == "leave_room":
                await self._handle_leave_room(data)

            elif message_type == "typing":
                await self._handle_typing(data)

            elif message_type == "send_message":
                await self._handle_send_message(data)

            else:
                await self._send_error("unknown_message_type", f"Unknown message type: {message_type}")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self._send_error("internal_error", str(e))

    async def _handle_ping(self):
        """Обработка ping сообщения"""
        await self.websocket.send_json({
            "type": "pong",
            "data": {
                "timestamp": datetime.utcnow().isoformat()
            }
        })

    async def _handle_join_room(self, data: dict):
        """Обработка вступления в комнату"""
        room_id = data.get("room_id")
        if not room_id:
            await self._send_error("invalid_params", "room_id is required")
            return

        try:
            room_uuid = uuid.UUID(room_id)
            manager.join_room(self.user_id, room_uuid)

            await self.websocket.send_json({
                "type": "room_joined",
                "data": {
                    "room_id": room_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            logger.info(f"User {self.user_id} joined room {room_id}")

        except ValueError:
            await self._send_error("invalid_room_id", "Invalid room ID format")

    async def _handle_leave_room(self, data: dict):
        """Обработка выхода из комнаты"""
        room_id = data.get("room_id")
        if not room_id:
            await self._send_error("invalid_params", "room_id is required")
            return

        try:
            room_uuid = uuid.UUID(room_id)
            manager.leave_room(self.user_id, room_uuid)

            await self.websocket.send_json({
                "type": "room_left",
                "data": {
                    "room_id": room_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            })

            logger.info(f"User {self.user_id} left room {room_id}")

        except ValueError:
            await self._send_error("invalid_room_id", "Invalid room ID format")

    async def _handle_typing(self, data: dict):
        """Обработка уведомления о наборе текста"""
        room_id = data.get("room_id")
        is_typing = data.get("is_typing", True)

        if not room_id:
            await self._send_error("invalid_params", "room_id is required")
            return

        try:
            room_uuid = uuid.UUID(room_id)
            await NotificationService.notify_typing(self.user_id, room_uuid, is_typing)

        except ValueError:
            await self._send_error("invalid_room_id", "Invalid room ID format")

    async def _handle_send_message(self, data: dict):
        """
        Обработка отправки сообщения через WebSocket

        Внимание: Основной способ отправки - REST API
        WebSocket используется только для доставки
        """
        # Эта функция будет интегрирована с MessageService позже
        await self._send_error("not_implemented", "Use REST API to send messages")

    async def _send_error(self, error_code: str, error_message: str):
        """Отправка ошибки клиенту"""
        await self.websocket.send_json({
            "type": "error",
            "data": {
                "error_code": error_code,
                "error_message": error_message,
                "timestamp": datetime.utcnow().isoformat()
            }
        })

    async def listen(self):
        """Слушать сообщения от клиента"""
        try:
            while True:
                data = await self.websocket.receive_text()
                message = json.loads(data)
                await self.handle_message(message)

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user {self.user_id}")
            await self.disconnect()

        except Exception as e:
            logger.error(f"WebSocket error for user {self.user_id}: {e}")
            await self.disconnect()
