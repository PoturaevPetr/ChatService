from typing import Dict, Any
from datetime import datetime

from server.crypto.utils import CryptoUtils


class KeyManager:
    """Утилиты для публичных ключей (генерация identity — только на клиенте)."""

    @staticmethod
    def export_public_key(public_key_pem: str, format: str = "pem") -> str:
        if format == "pem":
            return public_key_pem
        if format == "base64":
            return CryptoUtils.encode_base64(public_key_pem.encode("utf-8"))
        if format == "fingerprint":
            return CryptoUtils.hash_data(public_key_pem)
        raise ValueError(f"Unsupported format: {format}")
