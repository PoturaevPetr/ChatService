from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import json

from server.crypto.hybrid import HybridEncryption
from server.crypto.utils import CryptoUtils


class KeyManager:
    """Менеджер управления криптографическими ключами"""

    @staticmethod
    def generate_user_keypair(user_id: str) -> Dict[str, Any]:
        """
        Генерация ключевой пары для пользователя

        Args:
            user_id: UUID пользователя

        Returns:
            Dict с ключами и метаданными
        """
        private_pem, public_pem = HybridEncryption.generate_rsa_keypair()

        return {
            "user_id": user_id,
            "private_key": private_pem.decode('utf-8'),
            "public_key": public_pem.decode('utf-8'),
            "key_type": "RSA-4096",
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(days=365)).isoformat()
        }

    @staticmethod
    def export_public_key(public_key_pem: str, format: str = "pem") -> str:
        """
        Экспорт публичного ключа в différents форматы

        Args:
            public_key_pem: Публичный ключ в PEM формате
            format: 'pem', 'base64', 'fingerprint'

        Returns:
            Ключ в указанном формате
        """
        if format == "pem":
            return public_key_pem
        elif format == "base64":
            return CryptoUtils.encode_base64(public_key_pem.encode('utf-8'))
        elif format == "fingerprint":
            return CryptoUtils.hash_data(public_key_pem)
        else:
            raise ValueError(f"Unsupported format: {format}")

    @staticmethod
    def validate_key_pair(private_key_pem: str, public_key_pem: str) -> bool:
        """
        Проверка соответствия пары ключей

        Args:
            private_key_pem: Приватный ключ
            public_key_pem: Публичный ключ

        Returns:
            True если ключи соответствуют друг другу
        """
        try:
            # Пробуем зашифровать на публичном и расшифровать на приватном
            test_message = {"test": "validation"}
            encrypted = HybridEncryption.encrypt_message(
                test_message,
                public_key_pem.encode('utf-8')
            )

            decrypted = HybridEncryption.decrypt_message(
                encrypted["encrypted_data"],
                encrypted["encrypted_aes_key"],
                encrypted["nonce"],
                private_key_pem.encode('utf-8')
            )

            return decrypted == test_message
        except Exception:
            return False

    @staticmethod
    def rotate_key(old_private_key: str) -> Dict[str, Any]:
        """
        Ротация ключей (генерация новой пары)

        Args:
            old_private_key: Старый приватный ключ

        Returns:
            Dict с новой парой ключей
        """
        # Генерируем новую пару
        private_pem, public_pem = HybridEncryption.generate_rsa_keypair()

        return {
            "private_key": private_pem.decode('utf-8'),
            "public_key": public_pem.decode('utf-8'),
            "rotated_at": datetime.utcnow().isoformat()
        }
