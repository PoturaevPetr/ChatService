from typing import Optional, Dict, Any
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import uuid
import logging
from jose import JWTError

from server.auth.jwt_handler import jwt_handler
from server.auth.api_keys import api_key_manager
from server.database import get_db

logger = logging.getLogger(__name__)

# Security схемы
bearer_scheme = HTTPBearer()


class AuthMiddleware:
    """Middleware для аутентификации и авторизации"""

    @staticmethod
    async def verify_jwt_token(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
        """
        Верификация JWT токена

        Args:
            credentials: HTTP Authorization credentials

        Returns:
            Dict с данными пользователя

        Raises:
            HTTPException: Если токен невалиден
        """
        token = credentials.credentials

        try:
            payload = jwt_handler.verify_token(token, "access")
            return {
                "user_id": uuid.UUID(payload["sub"]),
                "service_id": payload["service_id"],
                "token_type": "jwt"
            }
        except ValueError as e:
            logger.warning(f"Invalid token type: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        except JWTError as e:
            logger.warning(f"Invalid token: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

    @staticmethod
    async def verify_api_key(request: Request) -> Optional[Dict[str, Any]]:
        """
        Верификация API ключа из заголовков

        Args:
            request: Starlette Request

        Returns:
            Dict с данными сервиса или None

        Raises:
            HTTPException: Если ключ невалиден
        """
        api_key = request.headers.get("X-API-Key")
        api_secret = request.headers.get("X-API-Secret")

        if not api_key or not api_secret:
            return None

        db = next(get_db())
        try:
            key_data = api_key_manager.validate_api_key(api_key, api_secret, db)
            if not key_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key or secret"
                )
            return {
                "service_id": key_data["service_id"],
                "key_id": key_data["key_id"],
                "token_type": "api_key",
                "permissions": key_data.get("permissions", [])
            }
        finally:
            db.close()

    @staticmethod
    async def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)
    ) -> Dict[str, Any]:
        """
        Получение текущего пользователя (JWT или API key)

        Args:
            request: Starlette Request
            credentials: HTTP Authorization credentials

        Returns:
            Dict с данными пользователя/сервиса

        Raises:
            HTTPException: Если аутентификация не прошла
        """
        # Сначала пробуем API ключ
        try:
            user_data = await AuthMiddleware.verify_api_key(request)
            if user_data:
                return user_data
        except HTTPException:
            pass

        # Затем пробуем JWT токен
        if credentials:
            return await AuthMiddleware.verify_jwt_token(credentials)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    async def require_permission(user_data: Dict[str, Any], required_permission: str) -> bool:
        """
        Проверка прав доступа

        Args:
            user_data: Данные пользователя
            required_permission: Требуемое разрешение

        Returns:
            True если разрешение есть

        Raises:
            HTTPException: Если разрешения нет
        """
        permissions = user_data.get("permissions", [])

        # Для API ключей проверяем права
        if user_data.get("token_type") == "api_key":
            if required_permission not in permissions:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{required_permission}' required"
                )
            return True

        # Для JWT токенов (пользователей) пока разрешаем всё
        return True


# Зависимость для FastAPI
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)
) -> Dict[str, Any]:
    """Зависимость для получения текущего пользователя"""
    return await AuthMiddleware.get_current_user(request, credentials)


# Middleware для добавления user_info в request.state
class AuthMiddlewareWrapper(BaseHTTPMiddleware):
    """Middleware wrapper для добавления данных аутентификации в request"""

    async def dispatch(self, request: Request, call_next):
        # Пропускаем health check и корень
        if request.url.path in ["/", "/health", "/docs", "/openapi.json"]:
            return await call_next(request)

        try:
            # Пытаемся аутентифицировать пользователя
            credentials = await bearer_scheme(request)
            user_data = await AuthMiddleware.verify_jwt_token(credentials)
            request.state.user = user_data
        except Exception:
            # Если не удалось аутентифицировать, продолжаем без пользователя
            request.state.user = None

        response = await call_next(request)
        return response
