from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect, status, HTTPException
from datetime import datetime
import uuid
import json
import logging

from server.websocket.manager import manager
from server.services.notification_service import NotificationService
from server.services.message_service import message_service
from server.services.users_services import users_service
from server.database import get_db
from server.database.RoomUsers import RoomUsers
from server.database.Rooms import Rooms

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
        try:
            from server.services.presence import set_user_node

            await set_user_node(self.user_id)
        except Exception as e:
            logger.debug("presence set on connect failed: %s", e)
        db_gen = get_db()
        db = next(db_gen)
        try:
            users_service.touch_last_seen_at(db, self.user_id)
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
        await NotificationService.notify_user_online(self.user_id)

        # Отправляем приветственное сообщение
        try:
            await self.websocket.send_json({
                "type": "connected",
                "data": {
                    "user_id": str(self.user_id),
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": "WebSocket connection established"
                }
            })
        except Exception as e:
            logger.debug("Failed to send welcome message on connect (socket already closed?): %s", e)

    async def disconnect(self):
        """Закрытие соединения"""
        try:
            uid = self.user_id
            # Сначала удаляем соединение из менеджера
            await manager.disconnect(self.websocket)
            # Проверяем, остались ли другие активные соединения
            still_online = manager.is_user_online(uid)
            if not still_online:
                # Только если нет других подключений — уведомляем об оффлайне
                await NotificationService.notify_user_offline(uid)
                try:
                    from server.services.presence import clear_user_node
                    from server.settings import settings

                    await clear_user_node(uid, only_if_node=settings.API_NODE_ID)
                except Exception as e:
                    logger.debug("presence clear on disconnect failed: %s", e)
                db_gen = get_db()
                db = next(db_gen)
                try:
                    users_service.touch_last_seen_at(db, uid)
                finally:
                    try:
                        next(db_gen)
                    except StopIteration:
                        pass
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

            elif message_type == "save_draft":
                await self._handle_save_draft(data)

            elif message_type == "delete_draft":
                await self._handle_delete_draft(data)

            else:
                await self._send_error("unknown_message_type", f"Unknown message type: {message_type}")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self._send_error("internal_error", str(e))

    async def _handle_ping(self):
        """Обработка ping сообщения"""
        try:
            from server.services.presence import touch_user_node

            await touch_user_node(self.user_id)
        except Exception:
            pass
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
            print(f"[API] Вход в чат: user={self.user_id} room={room_id}")

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

            print(f"[API] Выход из чата: user={self.user_id} room={room_id}")

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
        Отправка E2E-сообщения через WebSocket.
        Клиент обязан передать `e2e` (encrypted_data, nonce, recipient_keys).
        Сервер не принимает plaintext `message` для шифрования на своей стороне.
        """
        room_id = data.get("room_id")
        e2e_payload = data.get("e2e")

        if not room_id:
            await self._send_error("invalid_params", "room_id is required")
            return
        if e2e_payload is None:
            await self._send_error(
                "invalid_params",
                "e2e is required (server-side plaintext encryption removed)",
            )
            return

        try:
            room_uuid = uuid.UUID(room_id)
        except ValueError:
            await self._send_error("invalid_room_id", "Invalid room ID format")
            return

        db_gen = get_db()
        db = next(db_gen)
        try:
            sender_in_room = db.query(RoomUsers).filter(
                RoomUsers.room_id == room_uuid,
                RoomUsers.user_id == self.user_id,
            ).first()
            if not sender_in_room:
                await self._send_error("forbidden", "You are not in this room")
                return

            room = db.query(Rooms).filter(Rooms.id == room_uuid).first()
            if not room:
                await self._send_error("invalid_room_id", "Room not found")
                return

            member_rows = (
                db.query(RoomUsers.user_id)
                .filter(RoomUsers.room_id == room_uuid)
                .all()
            )
            member_ids = {r[0] for r in member_rows}
            is_direct = room.room_type == "direct"
            if is_direct:
                others = member_ids - {self.user_id}
                if len(others) != 1:
                    await self._send_error(
                        "invalid_params",
                        "Direct room must have exactly one other participant",
                    )
                    return
                recipient_id = next(iter(others))
            else:
                if len(member_ids) < 2:
                    await self._send_error("invalid_params", "No other participant in room")
                    return
                recipient_id = None

            if not isinstance(e2e_payload, dict):
                await self._send_error("invalid_params", "e2e must be an object")
                return

            from server.services.e2e_payload import parse_e2e_for_send

            try:
                enc_data_b64, nonce_b64, signature, _protocol, recipient_keys, device_keys = (
                    parse_e2e_for_send(e2e_payload, member_ids, db)
                )
            except HTTPException as he:
                detail = he.detail if isinstance(he.detail, str) else "invalid e2e"
                await self._send_error("invalid_params", detail)
                return

            message_data_for_meta: dict = {"_e2e": True}
            if data.get("e2e_suppress_push") is True:
                message_data_for_meta["_suppress_novu"] = True

            msg = await message_service.send_message(
                sender_id=self.user_id,
                recipient_id=recipient_id,
                message_data=message_data_for_meta,
                encrypted_data=enc_data_b64,
                nonce=nonce_b64,
                signature=signature,
                room_id=room_uuid,
                db=db,
                recipient_keys=recipient_keys,
                device_keys=device_keys or None,
            )

            # Автоматически очищаем черновик для этой комнаты при отправке сообщения
            try:
                from server.services.draft_service import draft_service
                await draft_service.delete_draft(self.user_id, room_uuid, db)
            except Exception as draft_err:
                logger.debug("Failed to auto-delete draft after send: %s", draft_err)

            await self.websocket.send_json({
                "type": "message_sent",
                "data": {
                    "message_id": str(msg.id),
                    "recipient_id": str(recipient_id) if recipient_id else None,
                    "room_id": room_id,
                    "sent_at": msg.sent_at.isoformat(),
                },
            })
            logger.info(
                f"Message {msg.id} sent via WebSocket from {self.user_id} "
                f"recipient_id={recipient_id} in room {room_id}"
            )
        except ValueError as e:
            await self._send_error("validation_error", str(e))
        except Exception as e:
            logger.exception(f"WebSocket send_message error: {e}")
            await self._send_error("internal_error", str(e))
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

    async def _handle_save_draft(self, data: dict):
        """Сохранить E2E-зашифрованный черновик сообщения."""
        room_id_raw = data.get("room_id")
        encrypted_data = data.get("encrypted_data")
        nonce = data.get("nonce")
        encrypted_aes_key = data.get("encrypted_aes_key")
        if not room_id_raw or not encrypted_data or not nonce or not encrypted_aes_key:
            return

        try:
            room_uuid = uuid.UUID(str(room_id_raw))
        except ValueError:
            return

        db_gen = get_db()
        db = next(db_gen)
        try:
            from server.services.draft_service import draft_service
            await draft_service.save_draft(
                user_id=self.user_id,
                room_id=room_uuid,
                encrypted_data=str(encrypted_data),
                nonce=str(nonce),
                encrypted_aes_key=str(encrypted_aes_key),
                db=db,
            )
        except Exception as e:
            logger.warning("Error saving draft via WS: %s", e)
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

    async def _handle_delete_draft(self, data: dict):
        """Удалить черновик сообщения."""
        room_id_raw = data.get("room_id")
        if not room_id_raw:
            return

        try:
            room_uuid = uuid.UUID(str(room_id_raw))
        except ValueError:
            return

        db_gen = get_db()
        db = next(db_gen)
        try:
            from server.services.draft_service import draft_service
            await draft_service.delete_draft(
                user_id=self.user_id,
                room_id=room_uuid,
                db=db,
            )
        except Exception as e:
            logger.warning("Error deleting draft via WS: %s", e)
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

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
            err_s = str(e).lower()
            if "close" in err_s or "closed" in err_s:
                logger.info(f"WebSocket connection closed for user {self.user_id}")
            else:
                logger.error(f"WebSocket error for user {self.user_id}: {e}")
            await self.disconnect()
