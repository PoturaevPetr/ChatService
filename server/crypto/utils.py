import base64
import secrets
from typing import Tuple
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


class CryptoUtils:
    """Утилиты для криптографических операций"""

    @staticmethod
    def generate_salt(length: int = 16) -> bytes:
        """Генерация случайной соли"""
        return secrets.token_bytes(length)

    @staticmethod
    def generate_key(length: int = 32) -> bytes:
        """Генерация случайного ключа"""
        return secrets.token_bytes(length)

    @staticmethod
    def encode_base64(data: bytes) -> str:
        """Кодирование в Base64"""
        return base64.b64encode(data).decode('utf-8')

    @staticmethod
    def decode_base64(data: str) -> bytes:
        """Декодирование из Base64"""
        return base64.b64decode(data.encode('utf-8'))

    @staticmethod
    def hash_data(data: str) -> str:
        """Хеширование данных"""
        digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
        digest.update(data.encode('utf-8'))
        return CryptoUtils.encode_base64(digest.finalize())
