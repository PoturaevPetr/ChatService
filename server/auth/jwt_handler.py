from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import uuid
from jose import jwt, JWTError
from passlib.context import CryptContext

from server.settings import settings

# Контекст для хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class JWTHandler:
    """Обработчик JWT токенов"""

    def __init__(self):
        self.secret_key = getattr(settings, 'JWT_SECRET_KEY', 'your-secret-key-change-in-production')
        self.algorithm = "HS256"
        self.access_token_expire_minutes = getattr(settings, 'ACCESS_TOKEN_EXPIRE_MINUTES', 30)
        self.refresh_token_expire_days = getattr(settings, 'REFRESH_TOKEN_EXPIRE_DAYS', 7)

    def create_access_token(self, user_id: uuid.UUID, service_id: str, additional_claims: Optional[Dict] = None) -> str:
        """
        Создание access токена

        Args:
            user_id: UUID пользователя
            service_id: ID сервиса
            additional_claims: Дополнительные claims

        Returns:
            JWT токен
        """
        claims = {
            "sub": str(user_id),
            "service_id": service_id,
            "type": "access",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes),
            "jti": str(uuid.uuid4())  # Уникальный ID токена
        }

        if additional_claims:
            claims.update(additional_claims)

        return jwt.encode(claims, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: uuid.UUID, service_id: str) -> str:
        """Создание refresh токена"""
        claims = {
            "sub": str(user_id),
            "service_id": service_id,
            "type": "refresh",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(days=self.refresh_token_expire_days),
            "jti": str(uuid.uuid4())
        }

        return jwt.encode(claims, self.secret_key, algorithm=self.algorithm)

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Декодирование и валидация токена

        Args:
            token: JWT токен

        Returns:
            Decoded claims

        Raises:
            JWTError: Ошибка токена (истек или невалиден)
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except JWTError as e:
            raise

    def verify_token(self, token: str, token_type: str = "access") -> Dict[str, Any]:
        """
        Верификация токена с проверкой типа

        Args:
            token: JWT токен
            token_type: Тип токена ('access' или 'refresh')

        Returns:
            Decoded claims

        Raises:
            ValueError: Неверный тип токена
            jwt.ExpiredSignatureError: Токен истек
            jwt.InvalidTokenError: Невалидный токен
        """
        payload = self.decode_token(token)

        if payload.get("type") != token_type:
            raise ValueError(f"Invalid token type. Expected {token_type}, got {payload.get('type')}")

        return payload

    def get_user_id_from_token(self, token: str) -> uuid.UUID:
        """Получение user_id из токена"""
        payload = self.verify_token(token, "access")
        return uuid.UUID(payload["sub"])

    def get_service_id_from_token(self, token: str) -> str:
        """Получение service_id из токена"""
        payload = self.verify_token(token, "access")
        return payload["service_id"]

    @staticmethod
    def hash_password(password: str) -> str:
        """Хеширование пароля"""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        return pwd_context.verify(plain_password, hashed_password)


# Глобальный экземпляр
jwt_handler = JWTHandler()
