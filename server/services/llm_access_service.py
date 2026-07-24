"""Выдача LLM credentials пользователю (RSA wrap для device identity)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from server.crypto.hybrid import HybridEncryption
from server.settings import settings


def llm_server_configured() -> bool:
    return bool(settings.OLLAMA_API_KEY and settings.OLLAMA_BASE_URL)


def build_encrypted_llm_credentials(device_public_pem: str) -> Dict[str, str]:
    if not settings.OLLAMA_API_KEY:
        raise ValueError("OLLAMA_API_KEY is not configured")
    pem = (device_public_pem or "").strip()
    if not pem:
        raise ValueError("device public key is required")

    payload: Dict[str, Any] = {"api_key": settings.OLLAMA_API_KEY}
    header = (settings.OLLAMA_API_KEY_HEADER or "").strip()
    if header:
        payload["api_key_header"] = header

    encrypted = HybridEncryption.encrypt_message(payload, pem.encode("utf-8"))
    return encrypted


def llm_access_meta() -> Dict[str, Optional[str]]:
    header = (settings.OLLAMA_API_KEY_HEADER or "").strip() or None
    return {
        "base_url": settings.OLLAMA_BASE_URL or None,
        "api_key_header": header,
    }
