"""
OAuth2: Google, Яндекс ID, VK (oauth.vk.com).
Конфигурация через переменные окружения (см. server/settings).
"""
from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlencode, quote

import httpx

from server.settings import settings

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

YANDEX_AUTH = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN = "https://oauth.yandex.ru/token"
YANDEX_INFO = "https://login.yandex.ru/info"

VK_AUTH = "https://oauth.vk.com/authorize"
VK_TOKEN = "https://oauth.vk.com/access_token"
VK_API = "https://api.vk.com/method/users.get"


@dataclass
class OAuthProfile:
    provider_user_id: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


def oauth_native_bridge_url() -> Optional[str]:
    """HTTPS redirect для нативного OAuth (принимается консолями). Пусто — мост отключён в валидации."""
    explicit = (getattr(settings, "OAUTH_NATIVE_CALLBACK_URL", None) or "").strip()
    if explicit:
        return explicit.rstrip("/")
    mob = (getattr(settings, "MOBILE_PUBLIC_BASE_URL", None) or "").strip()
    if mob:
        return f"{mob.rstrip('/')}/api/v1/auth/oauth/native-bridge"
    try:
        from urllib.parse import urlparse

        u = urlparse((getattr(settings, "API_BASE_URL", None) or "").strip())
        if u.scheme in ("http", "https") and u.netloc:
            return f"{u.scheme}://{u.netloc}/api/v1/auth/oauth/native-bridge".rstrip("/")
    except Exception:
        pass
    return None


def oauth_providers_configured() -> Dict[str, bool]:
    return {
        "google": bool(settings.OAUTH_GOOGLE_CLIENT_ID and settings.OAUTH_GOOGLE_CLIENT_SECRET),
        "yandex": bool(settings.OAUTH_YANDEX_CLIENT_ID and settings.OAUTH_YANDEX_CLIENT_SECRET),
        "vk": bool(settings.OAUTH_VK_APP_ID and settings.OAUTH_VK_SECURE_KEY),
    }


def _redirect_uri_allowed(redirect_uri: str) -> bool:
    from urllib.parse import urlparse

    raw = (redirect_uri or "").strip()
    if not raw:
        return False
    bridge = oauth_native_bridge_url()
    if bridge and raw.rstrip("/") == bridge.rstrip("/"):
        return True
    custom = getattr(settings, "OAUTH_CUSTOM_REDIRECT_URIS", None) or []
    if custom and raw in custom:
        return True
    p = urlparse(raw)
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    origin = f"{p.scheme}://{p.netloc}"
    path_ok = p.path.rstrip("/") == "/auth/oauth/callback"
    if not path_ok:
        return False
    allowed = getattr(settings, "OAUTH_FRONTEND_ORIGINS", None) or []
    return origin in allowed


def build_authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    if provider not in ("google", "yandex", "vk"):
        raise ValueError("Unknown provider")
    if not _redirect_uri_allowed(redirect_uri):
        raise ValueError("redirect_uri is not allowed")
    if provider == "google":
        if not oauth_providers_configured()["google"]:
            raise ValueError("Google OAuth is not configured")
        q = urlencode(
            {
                "client_id": settings.OAUTH_GOOGLE_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
            },
            quote_via=quote,
        )
        return f"{GOOGLE_AUTH}?{q}"
    if provider == "yandex":
        if not oauth_providers_configured()["yandex"]:
            raise ValueError("Yandex OAuth is not configured")
        q = urlencode(
            {
                "response_type": "code",
                "client_id": settings.OAUTH_YANDEX_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "state": state,
            },
            quote_via=quote,
        )
        return f"{YANDEX_AUTH}?{q}"
    if provider == "vk":
        if not oauth_providers_configured()["vk"]:
            raise ValueError("VK OAuth is not configured")
        q = urlencode(
            {
                "client_id": settings.OAUTH_VK_APP_ID,
                "display": "page",
                "redirect_uri": redirect_uri,
                "scope": "email",
                "response_type": "code",
                "v": "5.199",
                "state": state,
            },
            quote_via=quote,
        )
        return f"{VK_AUTH}?{q}"
    raise ValueError("Unknown provider")


async def exchange_code(provider: str, code: str, redirect_uri: str) -> OAuthProfile:
    if provider not in ("google", "yandex", "vk"):
        raise ValueError("Unknown provider")
    if not _redirect_uri_allowed(redirect_uri):
        raise ValueError("redirect_uri is not allowed")
    async with httpx.AsyncClient(timeout=20.0) as client:
        if provider == "google":
            return await _exchange_google(client, code, redirect_uri)
        if provider == "yandex":
            return await _exchange_yandex(client, code, redirect_uri)
        if provider == "vk":
            return await _exchange_vk(client, code, redirect_uri)
    raise ValueError("Unknown provider")


async def _exchange_google(client: httpx.AsyncClient, code: str, redirect_uri: str) -> OAuthProfile:
    r = await client.post(
        GOOGLE_TOKEN,
        data={
            "code": code,
            "client_id": settings.OAUTH_GOOGLE_CLIENT_ID,
            "client_secret": settings.OAUTH_GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code != 200:
        raise ValueError(f"Google token error: {r.status_code} {r.text[:200]}")
    data = r.json()
    access = data.get("access_token")
    if not access:
        raise ValueError("Google: no access_token")
    u = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"})
    if u.status_code != 200:
        raise ValueError(f"Google userinfo: {u.status_code}")
    info = u.json()
    sub = str(info.get("sub") or "").strip()
    if not sub:
        raise ValueError("Google: empty sub")
    return OAuthProfile(
        provider_user_id=sub,
        email=(str(info.get("email")).strip() if info.get("email") else None),
        first_name=(str(info.get("given_name")).strip() if info.get("given_name") else None),
        last_name=(str(info.get("family_name")).strip() if info.get("family_name") else None),
    )


async def _exchange_yandex(client: httpx.AsyncClient, code: str, redirect_uri: str) -> OAuthProfile:
    r = await client.post(
        YANDEX_TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.OAUTH_YANDEX_CLIENT_ID,
            "client_secret": settings.OAUTH_YANDEX_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code != 200:
        raise ValueError(f"Yandex token error: {r.status_code} {r.text[:200]}")
    data = r.json()
    access = data.get("access_token")
    if not access:
        raise ValueError("Yandex: no access_token")
    u = await client.get(YANDEX_INFO, headers={"Authorization": f"OAuth {access}"})
    if u.status_code != 200:
        raise ValueError(f"Yandex info: {u.status_code}")
    info = u.json()
    uid = str(info.get("id") or info.get("client_id") or "").strip()
    if not uid:
        raise ValueError("Yandex: empty id")
    fn = info.get("first_name") or info.get("real_name")
    ln = info.get("last_name")
    em = info.get("default_email") or info.get("login")
    return OAuthProfile(
        provider_user_id=uid,
        email=str(em).strip() if em else None,
        first_name=str(fn).strip() if fn else None,
        last_name=str(ln).strip() if ln else None,
    )


async def _exchange_vk(client: httpx.AsyncClient, code: str, redirect_uri: str) -> OAuthProfile:
    q = urlencode(
        {
            "client_id": settings.OAUTH_VK_APP_ID,
            "client_secret": settings.OAUTH_VK_SECURE_KEY,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        quote_via=quote,
    )
    r = await client.get(f"{VK_TOKEN}?{q}")
    if r.status_code != 200:
        raise ValueError(f"VK token error: {r.status_code} {r.text[:200]}")
    data = r.json()
    if "error" in data and data["error"]:
        raise ValueError(f"VK: {data.get('error_description', data.get('error'))}")
    user_id = data.get("user_id")
    access = data.get("access_token")
    if user_id is None or not access:
        raise ValueError("VK: missing user_id or access_token")
    uid = str(int(user_id))
    email = data.get("email")
    gr = await client.get(
        VK_API,
        params={"user_ids": uid, "fields": "first_name,last_name", "v": "5.199", "access_token": access},
    )
    fn: Optional[str] = None
    ln: Optional[str] = None
    if gr.status_code == 200:
        try:
            arr = gr.json().get("response") or []
            if arr and isinstance(arr[0], dict):
                fn = str(arr[0].get("first_name") or "").strip() or None
                ln = str(arr[0].get("last_name") or "").strip() or None
        except Exception:
            pass
    return OAuthProfile(
        provider_user_id=uid,
        email=str(email).strip() if email else None,
        first_name=fn,
        last_name=ln,
    )


def suggest_username(provider: str, subject: str) -> str:
    """Уникальный логин для users.username (до 100 символов)."""
    prefix = {"google": "g", "yandex": "ya", "vk": "vk"}.get(provider, "o")
    h = hashlib.sha256(f"{provider}:{subject}".encode()).hexdigest()[:10]
    tail = re.sub(r"[^a-zA-Z0-9_]", "_", subject)[-20:]
    base = f"{prefix}_{tail}_{h}" if tail else f"{prefix}_{h}"
    if len(base) > 90:
        base = f"{prefix}_{h}"
    return base[:100]


def unique_username(db, base: str) -> str:
    from server.database.Users import Users

    name = base[:100]
    n = 0
    while db.query(Users).filter(Users.username == name).first():
        suffix = secrets.token_hex(2)
        name = f"{base[:80]}_{suffix}"[:100]
        n += 1
        if n > 50:
            name = f"oauth_{secrets.token_hex(8)}"[:100]
    return name
