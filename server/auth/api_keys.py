from typing import Dict, Optional, List
from datetime import datetime, timedelta
import secrets
import uuid

from server.database import get_db
from server.database.Users import Users
from sqlalchemy.orm import Session


class APIKeyManager:
    """Менеджер API ключей для сервисов"""

    # Префиксы для разных типов ключей
    KEY_PREFIXES = {
        "service": "svc",
        "user": "usr",
        "admin": "adm"
    }

    @staticmethod
    def generate_api_key(key_type: str = "service") -> str:
        """
        Генерация API ключа

        Args:
            key_type: Тип ключа ('service', 'user', 'admin')

        Returns:
            API ключ в формате: prefix_key
        """
        prefix = APIKeyManager.KEY_PREFIXES.get(key_type, "key")
        random_part = secrets.token_urlsafe(32)
        return f"{prefix}_{random_part}"

    @staticmethod
    def generate_secret() -> str:
        """Генерация секретного ключа"""
        return secrets.token_urlsafe(64)

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        """Хеширование API ключа для хранения"""
        # Используем хеширование для безопасности
        import hashlib
        return hashlib.sha256(api_key.encode()).hexdigest()

    @staticmethod
    def verify_api_key(api_key: str, hashed_key: str) -> bool:
        """Проверка API ключа"""
        import hashlib
        return hashlib.sha256(api_key.encode()).hexdigest() == hashed_key

    @staticmethod
    def create_service_key(
        service_id: str,
        db: Session,
        name: Optional[str] = None,
        expires_in_days: Optional[int] = None
    ) -> Dict[str, str]:
        """
        Создание API ключа для сервиса

        Args:
            service_id: ID сервиса
            db: Сессия БД
            name: Название ключа (опционально)
            expires_in_days: Срок действия в днях (опционально)

        Returns:
            Dict с api_key и secret
        """
        from server.database.APIKeys import APIKeys

        # Генерируем ключ и секрет
        api_key = APIKeyManager.generate_api_key("service")
        secret = APIKeyManager.generate_secret()

        # Создаем запись в БД
        key_data = {
            "key_hash": APIKeyManager.hash_api_key(api_key),
            "service_id": service_id,
            "name": name or f"Service key for {service_id}",
            "secret_hash": APIKeyManager.hash_api_key(secret),
            "is_active": True,
            "expires_at": datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None
        }

        db_key = APIKeys(**key_data)
        db.add(db_key)
        db.commit()
        db.refresh(db_key)

        return {
            "api_key": api_key,
            "secret": secret,
            "key_id": str(db_key.id),
            "expires_at": db_key.expires_at.isoformat() if db_key.expires_at else None
        }

    @staticmethod
    def validate_api_key(api_key: str, secret: str, db: Session) -> Optional[Dict]:
        """
        Валидация API ключа

        Args:
            api_key: API ключ
            secret: Секретный ключ
            db: Сессия БД

        Returns:
            Dict с данными ключа или None
        """
        from server.database.APIKeys import APIKeys

        key_hash = APIKeyManager.hash_api_key(api_key)
        secret_hash = APIKeyManager.hash_api_key(secret)

        db_key = db.query(APIKeys).filter(
            APIKeys.key_hash == key_hash,
            APIKeys.secret_hash == secret_hash,
            APIKeys.is_active == True
        ).first()

        if not db_key:
            return None

        # Проверяем срок действия
        if db_key.expires_at and datetime.utcnow() > db_key.expires_at:
            db_key.is_active = False
            db.commit()
            return None

        return {
            "key_id": str(db_key.id),
            "service_id": db_key.service_id,
            "name": db_key.name,
            "permissions": db_key.permissions or []
        }

    @staticmethod
    def revoke_key(key_id: uuid.UUID, db: Session) -> bool:
        """Отзыв API ключа"""
        from server.database.APIKeys import APIKeys

        db_key = db.query(APIKeys).filter(APIKeys.id == key_id).first()
        if db_key:
            db_key.is_active = False
            db_key.revoked_at = datetime.utcnow()
            db.commit()
            return True
        return False


# Глобальный экземпляр
api_key_manager = APIKeyManager()
