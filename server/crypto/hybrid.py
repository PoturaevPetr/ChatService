from typing import Tuple, Dict, Any
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
import json

from server.crypto.utils import CryptoUtils


class HybridEncryption:
    """
    Гибридная система шифрования:
    - AES-256-GCM для шифрования данных
    - RSA-4096 для шифрования ключа AES
    """

    # Размеры ключей
    AES_KEY_SIZE = 32  # 256 бит
    AES_NONCE_SIZE = 12  # 96 бит для GCM
    RSA_KEY_SIZE = 4096

    @staticmethod
    def generate_rsa_keypair() -> Tuple[bytes, bytes]:
        """
        Генерация пары RSA ключей

        Returns:
            Tuple[private_key_pem, public_key_pem]
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=HybridEncryption.RSA_KEY_SIZE,
            backend=default_backend()
        )

        # Сериализация приватного ключа
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        # Сериализация публичного ключа
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        return private_pem, public_pem

    @staticmethod
    def encrypt_message(message: Dict[str, Any], recipient_public_key_pem: bytes) -> Dict[str, str]:
        """
        Шифрование сообщения гибридным методом

        Args:
            message: Исходное сообщение (dict)
            recipient_public_key_pem: Публичный ключ получателя в PEM формате

        Returns:
            Dict с зашифрованными данными:
            {
                "encrypted_data": base64(encrypted_message),
                "encrypted_aes_key": base64(rsa_encrypted_aes_key),
                "nonce": base64(nonce)
            }
        """
        # 1. Сериализуем сообщение в JSON
        message_json = json.dumps(message, ensure_ascii=False).encode('utf-8')

        # 2. Генерируем AES ключ и nonce
        aes_key = CryptoUtils.generate_key(HybridEncryption.AES_KEY_SIZE)
        nonce = CryptoUtils.generate_salt(HybridEncryption.AES_NONCE_SIZE)

        # 3. Шифруем данные AES-256-GCM
        aesgcm = AESGCM(aes_key)
        encrypted_data = aesgcm.encrypt(nonce, message_json, None)

        # 4. Загружаем публичный ключ RSA получателя
        public_key = serialization.load_pem_public_key(
            recipient_public_key_pem,
            backend=default_backend()
        )

        # 5. Шифруем AES ключ RSA
        encrypted_aes_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # 6. Возвращаем результат в Base64
        return {
            "encrypted_data": CryptoUtils.encode_base64(encrypted_data),
            "encrypted_aes_key": CryptoUtils.encode_base64(encrypted_aes_key),
            "nonce": CryptoUtils.encode_base64(nonce)
        }

    @staticmethod
    def decrypt_message(
        encrypted_data_b64: str,
        encrypted_aes_key_b64: str,
        nonce_b64: str,
        private_key_pem: bytes
    ) -> Dict[str, Any]:
        """
        Дешифрование сообщения

        Args:
            encrypted_data_b64: Зашифрованные данные (Base64)
            encrypted_aes_key_b64: Зашифрованный AES ключ (Base64)
            nonce_b64: Nonce для AES-GCM (Base64)
            private_key_pem: Приватный ключ в PEM формате

        Returns:
            Расшифрованное сообщение (dict)
        """
        # 1. Декодируем из Base64
        encrypted_data = CryptoUtils.decode_base64(encrypted_data_b64)
        encrypted_aes_key = CryptoUtils.decode_base64(encrypted_aes_key_b64)
        nonce = CryptoUtils.decode_base64(nonce_b64)

        # 2. Загружаем приватный ключ RSA
        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
            backend=default_backend()
        )

        # 3. Расшифровываем AES ключ RSA
        aes_key = private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # 4. Расшифровываем данные AES-256-GCM
        aesgcm = AESGCM(aes_key)
        decrypted_data = aesgcm.decrypt(nonce, encrypted_data, None)

        # 5. Десериализуем JSON
        return json.loads(decrypted_data.decode('utf-8'))

    @staticmethod
    def sign_message(message: str, private_key_pem: bytes) -> str:
        """
        Создание цифровой подписи сообщения

        Args:
            message: Сообщение для подписи
            private_key_pem: Приватный ключ в PEM формате

        Returns:
            Подпись в Base64
        """
        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
            backend=default_backend()
        )

        message_bytes = message.encode('utf-8')
        signature = private_key.sign(
            message_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )

        return CryptoUtils.encode_base64(signature)

    @staticmethod
    def verify_signature(message: str, signature_b64: str, public_key_pem: bytes) -> bool:
        """
        Проверка цифровой подписи

        Args:
            message: Исходное сообщение
            signature_b64: Подпись в Base64
            public_key_pem: Публичный ключ в PEM формате

        Returns:
            True если подпись верна
        """
        try:
            public_key = serialization.load_pem_public_key(
                public_key_pem,
                backend=default_backend()
            )

            message_bytes = message.encode('utf-8')
            signature = CryptoUtils.decode_base64(signature_b64)

            public_key.verify(
                signature,
                message_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
        except Exception:
            return False
