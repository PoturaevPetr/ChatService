from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from typing import Optional
import uuid
import logging
from jose import JWTError

from server.auth.jwt_handler import jwt_handler
from server.websocket.handlers import WebSocketHandler
from server.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws")
@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: Optional[str] = None,
    token: Optional[str] = Query(None)
):
    """
    WebSocket endpoint для real-time обмена сообщениями

    Параметры:
    - **user_id**: UUID пользователя (опционально, если не указан - берется из токена)
    - **token**: JWT access токен (query parameter)

    Сообщения от клиента должны быть в формате:
    {
        "type": "message_type",
        "data": { ... }
    }

    Поддерживаемые типы сообщений:
    - **ping**: Проверка соединения
    - **join_room**: Вступление в комнату (data: {room_id})
    - **leave_room**: Выход из комнаты (data: {room_id})
    - **typing**: Уведомление о наборе текста (data: {room_id, is_typing})
    """
    try:
        # Проверка токена
        if not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            logger.warning("WebSocket connection attempt without token")
            return

        try:
            payload = jwt_handler.verify_token(token, "access")
            token_user_id = uuid.UUID(payload["sub"])

            # Если user_id указан в пути, проверяем что токен принадлежит этому пользователю
            if user_id:
                try:
                    user_uuid = uuid.UUID(user_id)
                    if token_user_id != user_uuid:
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        logger.warning(f"Token user_id {token_user_id} != websocket user_id {user_uuid}")
                        return
                except ValueError:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    logger.warning(f"Invalid user_id format: {user_id}")
                    return
            else:
                # Если user_id не указан, используем ID из токена
                user_uuid = token_user_id

        except JWTError as e:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            logger.warning(f"Invalid token for WebSocket: {e}")
            return
        except Exception as e:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            logger.warning(f"Unexpected error: {e}")
            return

        # Создаем обработчик WebSocket
        handler = WebSocketHandler(websocket, user_uuid, token)

        # Устанавливаем соединение
        await handler.connect()

        # Слушаем сообщения
        await handler.listen()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
