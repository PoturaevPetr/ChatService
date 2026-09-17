import json
from typing import Dict, Any, Optional, Literal, List
from fastapi import APIRouter, HTTPException, Depends, status, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
import uuid
from jose import jwt, JWTError
from sqlalchemy import inspect

from server.database import get_db
from server.database.Users import Users
from server.database.Sessions import Sessions
from server.database.OAuthAccounts import OAuthAccounts
from server.auth.jwt_handler import jwt_handler
from server.auth.middleware import get_current_user
from server.settings import settings
from sqlalchemy.orm import Session
from datetime import date

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

_HAS_PASSWORD_HASH: Optional[bool] = None


def _users_password_hash_supported(db: Session) -> bool:
    """Check if users.password_hash exists in current DB schema."""
    global _HAS_PASSWORD_HASH
    if _HAS_PASSWORD_HASH is not None:
        return _HAS_PASSWORD_HASH
    try:
        cols = inspect(db.bind).get_columns("users")
        _HAS_PASSWORD_HASH = any(c.get("name") == "password_hash" for c in cols)
    except Exception:
        _HAS_PASSWORD_HASH = False
    return _HAS_PASSWORD_HASH


def _get_password_hash(db: Session, user_id: uuid.UUID) -> Optional[str]:
    if not _users_password_hash_supported(db):
        return None
    try:
        user = db.query(Users).filter(Users.id == user_id).first()
    except Exception:
        return None
    if not user:
        return None
    raw = user.password_hash
    if not raw or not isinstance(raw, str):
        return None
    value = raw.strip()
    return value if value else None


def _set_password_hash(db: Session, user_id: uuid.UUID, password_hash: str) -> bool:
    if not _users_password_hash_supported(db):
        return False
    try:
        n = (
            db.query(Users)
            .filter(Users.id == user_id)
            .update({"password_hash": password_hash}, synchronize_session=False)
        )
        return n > 0
    except Exception:
        return False


# Pydantic модели для запросов/ответов
class RegisterRequest(BaseModel):
    username: str = Field(..., description="Уникальное имя пользователя")
    service_id: str = Field(..., description="Идентификатор сервиса-клиента")
    password: Optional[str] = None  # Опционально для внешних сервисов
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    birth_date: Optional[date] = None
    avatar: Optional[str] = None
    public_key: Optional[str] = Field(
        None,
        description="DEPRECATED V3.5 — ignored; keys via POST /devices/register",
    )


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    public_key: Optional[str] = None
    access_token: str
    refresh_token: str


class LoginRequest(BaseModel):
    username: str
    service_id: str
    password: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: uuid.UUID
    username: str


class DeviceLinkExchangePrekeyIn(BaseModel):
    key_id: int = Field(..., ge=1)
    public_key: str = Field(..., min_length=16)


class DeviceLinkRegisterIn(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=64)
    name: Optional[str] = Field(None, max_length=255)
    platform: str = Field("web", max_length=32)
    identity_key_public: str = Field(..., min_length=16)
    signal_identity_key_public: Optional[str] = None
    registration_id: int = Field(0, ge=0)
    signed_prekey_id: Optional[int] = None
    signed_prekey_public: Optional[str] = None
    signed_prekey_signature: Optional[str] = None
    one_time_prekeys: List[DeviceLinkExchangePrekeyIn] = Field(default_factory=list)


class DeviceLinkExchangeRequest(DeviceLinkRegisterIn):
    """QR/code login on a new device — no JWT; trusted device created the code."""

    code: str = Field(..., min_length=4, max_length=16)
    service_id: str = Field(..., min_length=1, max_length=64)


class DeviceLinkExchangeResponse(LoginResponse):
    linked: bool = True
    device_id: str


class DeviceLinkRequestResponse(BaseModel):
    request_id: uuid.UUID
    code: str
    expires_at: str
    qr_payload: str


class DeviceLinkPollResponse(BaseModel):
    status: Literal["pending", "approved", "expired"]
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user_id: Optional[uuid.UUID] = None
    username: Optional[str] = None
    encrypted_master_key: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str

class UpdateUserRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    birth_date: Optional[date] = None
    avatar: Optional[str] = None

class UpdateUserResponce(BaseModel):
    id: uuid.UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    birth_date: Optional[date] = None
    avatar: Optional[str] = None

class UserResponce(BaseModel):
    id: uuid.UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    birth_date: Optional[date] = None
    avatar: Optional[str] = None

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Регистрация. Crypto keys — POST /devices/register после получения JWT.
    """
    existing_user = db.query(Users).filter(
        Users.username == request.username,
        Users.service_id == request.service_id
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already exists"
        )

    try:
        user = Users()
        user.username=request.username
        user.service_id=request.service_id
        user.first_name=request.first_name
        user.middle_name=request.middle_name
        user.last_name=request.last_name
        user.avatar=request.avatar
        user.birth_date=request.birth_date
        user.is_active=True
        user.is_verified=False
        db.add(user)
        db.flush()

        if _users_password_hash_supported(db):
            if not request.password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password is required"
                )
            _set_password_hash(db, user.id, jwt_handler.hash_password(request.password))

        access_token = jwt_handler.create_access_token(user.id, request.service_id)
        refresh_token = jwt_handler.create_refresh_token(user.id, request.service_id)

        session = Sessions(
            user_id=user.id,
            token_jti=jwt_handler.decode_token(access_token)["jti"],
            refresh_token=refresh_token,
            service_id=request.service_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=jwt_handler.refresh_token_expire_days)
        )
        db.add(session)
        db.commit()

        return RegisterResponse(
            user_id=user.id,
            username=user.username,
            public_key=None,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

@router.post("/update", response_model=UpdateUserResponce)
async def update(
    request: UpdateUserRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обновление данных пользователя
    """
    print(current_user)
    user: Users = db.query(Users).get(current_user.get("user_id"))

    # Partial update: не затираем поля, которых нет в запросе.
    # Важно: если фронт отправляет только `avatar`, то остальные поля будут `None`
    # и иначе их можно было бы случайно перезаписать в БД на NULL.
    data = request.model_dump(exclude_unset=True)
    if "first_name" in data:
        user.first_name = data["first_name"]
    if "middle_name" in data:
        user.middle_name = data["middle_name"]
    if "last_name" in data:
        user.last_name = data["last_name"]
    if "avatar" in data:
        user.avatar = data["avatar"]
    if "birth_date" in data:
        user.birth_date = data["birth_date"]
    db.commit()
    db.refresh(user)
    return user

@router.get("/me", response_model=UserResponce)
async def me(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user: Users = db.query(Users).get(current_user.get("user_id"))
    return user
    
@router.post("/device-link/exchange", response_model=DeviceLinkExchangeResponse)
async def device_link_exchange(
    request: DeviceLinkExchangeRequest,
    db: Session = Depends(get_db),
):
    """
    New device: exchange QR/code from a trusted logged-in device for JWT session.
    Registers device keys, marks link challenge consumed, returns tokens.
    """
    from server.database.DeviceLinkChallenges import DeviceLinkChallenges
    from server.services.device_service import (
        DeviceRegisterPayload,
        consume_link_challenge,
        get_active_user,
        upsert_user_device,
    )

    normalized = request.code.strip().upper()
    now = datetime.now(timezone.utc)
    challenge = (
        db.query(DeviceLinkChallenges)
        .filter(
            DeviceLinkChallenges.code == normalized,
            DeviceLinkChallenges.consumed_at.is_(None),
        )
        .first()
    )
    if not challenge or challenge.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired link code",
        )

    try:
        user = get_active_user(db, challenge.user_id)
        consume_link_challenge(
            db,
            user_id=challenge.user_id,
            code=normalized,
            new_device_id=request.device_id.strip(),
        )
        payload = DeviceRegisterPayload(
            device_id=request.device_id,
            name=request.name,
            platform=request.platform,
            identity_key_public=request.identity_key_public,
            signal_identity_key_public=request.signal_identity_key_public,
            registration_id=request.registration_id,
            signed_prekey_id=request.signed_prekey_id,
            signed_prekey_public=request.signed_prekey_public,
            signed_prekey_signature=request.signed_prekey_signature,
            one_time_prekeys=request.one_time_prekeys,
        )
        device = upsert_user_device(db, user.id, payload)
        device.linked_at = now
        device.last_seen_at = now
        access_token, refresh_token = _create_tokens_and_session(db, user, request.service_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        msg = str(e)
        if "expired" in msg.lower() or "invalid" in msg.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e
        if "same device" in msg.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e
        if "disabled" in msg.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return DeviceLinkExchangeResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.id,
        username=user.username,
        linked=True,
        device_id=device.device_id,
    )


@router.post("/device-link/request", response_model=DeviceLinkRequestResponse)
async def device_link_request(
    request: DeviceLinkRegisterIn,
    db: Session = Depends(get_db),
):
    """
    Desktop/web waiting login: show QR (kindred-login:CODE) for trusted phone to approve.
    Body matches exchange (device keys) except `code` is ignored.
    """
    import json
    from datetime import timedelta
    from server.database.DeviceLoginPending import DeviceLoginPending
    from server.services.device_service import DeviceRegisterPayload, make_link_code, payload_to_dict

    now = datetime.now(timezone.utc)
    code = make_link_code()
    for _ in range(5):
        exists = (
            db.query(DeviceLoginPending)
            .filter(
                DeviceLoginPending.code == code,
                DeviceLoginPending.consumed_at.is_(None),
                DeviceLoginPending.expires_at > now,
            )
            .first()
        )
        if not exists:
            break
        code = make_link_code()

    payload = DeviceRegisterPayload(
        device_id=request.device_id,
        name=request.name,
        platform=request.platform,
        identity_key_public=request.identity_key_public,
        signal_identity_key_public=request.signal_identity_key_public,
        registration_id=request.registration_id,
        signed_prekey_id=request.signed_prekey_id,
        signed_prekey_public=request.signed_prekey_public,
        signed_prekey_signature=request.signed_prekey_signature,
        one_time_prekeys=request.one_time_prekeys,
    )
    expires = now + timedelta(seconds=60)
    row = DeviceLoginPending(
        code=code,
        expires_at=expires,
        device_payload_json=json.dumps(payload_to_dict(payload)),
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return DeviceLinkRequestResponse(
        request_id=row.id,
        code=code,
        expires_at=expires.isoformat(),
        qr_payload=f"kindred-login:{code}",
    )


@router.get("/device-link/poll/{request_id}", response_model=DeviceLinkPollResponse)
async def device_link_poll(
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Poll pending desktop login; returns tokens once after trusted device approved."""
    from server.database.DeviceLoginPending import DeviceLoginPending

    now = datetime.now(timezone.utc)
    row = db.query(DeviceLoginPending).filter(DeviceLoginPending.id == request_id).first()
    if not row:
        return DeviceLinkPollResponse(status="expired")
    if row.expires_at < now and not row.access_token:
        return DeviceLinkPollResponse(status="expired")
    if row.access_token and row.refresh_token and row.user_id:
        user = db.query(Users).filter(Users.id == row.user_id).first()
        username = user.username if user else ""
        row.consumed_at = now
        access_token = row.access_token
        refresh_token = row.refresh_token
        user_id = row.user_id
        encrypted_master_key = row.encrypted_master_key
        row.access_token = None
        row.refresh_token = None
        row.encrypted_master_key = None
        db.commit()
        return DeviceLinkPollResponse(
            status="approved",
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
            username=username,
            encrypted_master_key=encrypted_master_key,
        )
    return DeviceLinkPollResponse(status="pending")


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Аутентификация пользователя

    - **username**: Имя пользователя
    - **service_id**: Идентификатор сервиса
    - **password**: Пароль (опционально)
    """
    # Ищем пользователя
    user: Users = db.query(Users).filter(
        Users.username == request.username,
        Users.service_id == request.service_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    if not _users_password_hash_supported(db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth schema is outdated: users.password_hash is missing. Apply migration add_users_password_hash.sql"
        )

    stored_password_hash = _get_password_hash(db, user.id)
    if not stored_password_hash:
        # Аккаунт привязан к OAuth — нельзя «привязать» пароль по одному вводу логина/пароля.
        if db.query(OAuthAccounts).filter(OAuthAccounts.user_id == user.id).first():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        # Legacy account bootstrap:
        # if user provides a password, bind it to account on first successful login.
        if not request.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password is not configured for this account"
            )
        new_password_hash = jwt_handler.hash_password(request.password)
        saved = _set_password_hash(db, user.id, new_password_hash)
        if not saved:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to verify account password. Please retry login."
            )
        # Use freshly generated hash in-memory to avoid false negatives from read-after-write edge cases.
        stored_password_hash = new_password_hash
    if not request.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password required"
        )
    try:
        password_ok = jwt_handler.verify_password(request.password, stored_password_hash)
    except Exception:
        # Corrupted/unsupported hash in DB should not crash endpoint.
        password_ok = False
    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Seamless migration: if user logged in with legacy bcrypt hash, rehash to bcrypt_sha256.
    if isinstance(stored_password_hash, str) and stored_password_hash.startswith("$2"):
        _set_password_hash(db, user.id, jwt_handler.hash_password(request.password))

    # Создаем токены
    access_token = jwt_handler.create_access_token(user.id, request.service_id)
    refresh_token = jwt_handler.create_refresh_token(user.id, request.service_id)

    # Обновляем last_login
    user.last_login = datetime.now(timezone.utc)

    # Создаем сессию
    session = Sessions(
        user_id=user.id,
        token_jti=jwt_handler.decode_token(access_token)["jti"],
        refresh_token=refresh_token,
        service_id=request.service_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=jwt_handler.refresh_token_expire_days)
    )
    db.add(session)

    db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.id,
        username=user.username,
        
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Обновление access токена через refresh токен
    """
    try:
        print("1. Starting refresh token process")
        payload = jwt_handler.verify_token(request.refresh_token, "refresh")
        print(f"2. Payload: {payload}")
        
        user_id = uuid.UUID(payload["sub"])
        service_id = payload["service_id"]
        
        # Проверяем сессию
        print("3. Querying session")
        session: Sessions = db.query(Sessions).filter(
            Sessions.refresh_token == request.refresh_token,
            Sessions.user_id == user_id
        ).first()
        print(f"4. Session found: {session}")
        
        if not session or not session.is_valid():
            print("5. Session is invalid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        print("5. Session is valid")
        
        # Создаем новые токены
        print("6. Creating new tokens")
        new_access_token = jwt_handler.create_access_token(user_id, service_id)
        new_refresh_token = jwt_handler.create_refresh_token(user_id, service_id)
        print(f"7. New tokens created - Access: {new_access_token[:20]}..., Refresh: {new_refresh_token[:20]}...")
        
        # Обновляем refresh-сессию и jti access-токена
        print("8. Updating session")
        session.refresh_token = new_refresh_token
        session.token_jti = jwt_handler.decode_token(new_access_token)["jti"]
        new_expires_at = datetime.now(timezone.utc) + timedelta(days=jwt_handler.refresh_token_expire_days)
        session.expires_at = new_expires_at
        print(f"9. New refresh-session expires_at: {new_expires_at}")
        
        print("10. Committing to database")
        db.commit()
        print("11. Database commit successful")
        
        response = RefreshTokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token
        )
        print("12. Returning response")
        return response

    except ValueError as e:
        print(f"ValueError: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except JWTError as e:
        print(f"JWTError: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except HTTPException:
        # Пробрасываем HTTP исключения дальше
        raise
    except Exception as e:
        # Логируем ошибку с полным traceback
        import traceback
        print(f"Internal server error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        
        # Проверяем состояние сессии
        if 'session' in locals():
            print(f"Session state before error: {session.__dict__}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error occurred: {str(e)}"  # Временно показываем ошибку для отладки
        )

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    refresh_token: str,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Выход из системы (отзыв токена)
    """
    # Отзываем refresh токен
    session = db.query(Sessions).filter(
        Sessions.refresh_token == refresh_token,
        Sessions.user_id == current_user["user_id"]
    ).first()

    if session:
        session.revoke()
        db.commit()

    return None


OAuthProviderType = Literal["google", "yandex", "vk"]


class OAuthExchangeRequest(BaseModel):
    provider: OAuthProviderType
    code: str = Field(..., min_length=1, max_length=4096)
    redirect_uri: str = Field(..., min_length=8, max_length=2048)
    service_id: str = Field(default="chatApp", max_length=100)
    public_key: Optional[str] = Field(
        None,
        description="PEM public key с клиента (обязателен для нового пользователя)",
    )


class OAuthExchangeResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: uuid.UUID
    username: str
    is_new_user: bool
    public_key: Optional[str] = None


def _create_tokens_and_session(db: Session, user: Users, service_id: str) -> tuple[str, str]:
    access_token = jwt_handler.create_access_token(user.id, service_id)
    refresh_token = jwt_handler.create_refresh_token(user.id, service_id)
    session = Sessions(
        user_id=user.id,
        token_jti=jwt_handler.decode_token(access_token)["jti"],
        refresh_token=refresh_token,
        service_id=service_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=jwt_handler.refresh_token_expire_days),
    )
    db.add(session)
    user.last_login = datetime.now(timezone.utc)
    return access_token, refresh_token


@router.get("/oauth/providers")
async def oauth_providers_list():
    """Какие провайдеры настроены на сервере (по env)."""
    from server.oauth_providers import oauth_providers_configured

    return oauth_providers_configured()


@router.get("/oauth/native-bridge", response_class=HTMLResponse, include_in_schema=False)
async def oauth_native_bridge():
    """
    HTTPS redirect URI для консолей Google/Яндекс (без custom scheme).
    Провайдер возвращает сюда ?code=&state=; страница перенаправляет в приложение.
    """
    scheme = (getattr(settings, "OAUTH_APP_RETURN_SCHEME", None) or "com.kindred.messapp").strip() or "com.kindred.messapp"
    deep = f"{scheme}://auth/oauth/callback"
    deep_js = json.dumps(deep)
    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/></head>
<body style="margin:0;font-family:system-ui,sans-serif;text-align:center;padding:2rem;background:#f8f9fb;color:#1a1a1a">
<p style="margin:0 0 1rem">Возврат в Kindred…</p>
<script>
(function() {{
  var q = window.location.search || '';
  var t = {deep_js} + q;
  try {{ window.location.replace(t); }} catch (e) {{}}
  setTimeout(function() {{
    var p = document.createElement('p');
    var a = document.createElement('a');
    a.href = t;
    a.textContent = 'Открыть приложение';
    p.appendChild(a);
    document.body.appendChild(p);
  }}, 1800);
}})();
</script>
</body></html>"""
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@router.get("/oauth/authorize-url")
async def oauth_authorize_url(
    provider: OAuthProviderType = Query(...),
    redirect_uri: str = Query(..., min_length=8, max_length=2048),
    state: str = Query(..., min_length=8, max_length=256),
):
    """URL для редиректа пользователя на страницу провайдера."""
    from server.oauth_providers import build_authorize_url

    try:
        url = build_authorize_url(provider, redirect_uri, state)
        return {"authorization_url": url}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/oauth/exchange", response_model=OAuthExchangeResponse)
async def oauth_exchange(request: OAuthExchangeRequest, db: Session = Depends(get_db)):
    """
    Обмен authorization code на JWT.
    Keys: POST /devices/register после логина.
    """
    from server.oauth_providers import exchange_code, suggest_username, unique_username

    service_id = (request.service_id or "chatApp").strip() or "chatApp"
    try:
        profile = await exchange_code(request.provider, request.code.strip(), request.redirect_uri.strip())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    link = (
        db.query(OAuthAccounts)
        .filter(
            OAuthAccounts.provider == request.provider,
            OAuthAccounts.provider_user_id == profile.provider_user_id,
        )
        .first()
    )

    if link:
        user = db.query(Users).filter(Users.id == link.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled")
        try:
            access_token, refresh_token = _create_tokens_and_session(db, user, service_id)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return OAuthExchangeResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user.id,
            username=user.username,
            is_new_user=False,
        )

    # New user — crypto keys via /devices/register after JWT
    base_username = suggest_username(request.provider, profile.provider_user_id)
    username = unique_username(db, base_username)

    try:
        user = Users()
        user.username = username
        user.service_id = service_id
        user.first_name = profile.first_name
        user.last_name = profile.last_name
        user.middle_name = None
        user.birth_date = None
        user.avatar = None
        user.is_active = True
        user.is_verified = True
        db.add(user)
        db.flush()

        db.add(
            OAuthAccounts(
                user_id=user.id,
                provider=request.provider,
                provider_user_id=profile.provider_user_id,
            )
        )

        access_token, refresh_token = _create_tokens_and_session(db, user, service_id)
        db.commit()

        return OAuthExchangeResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user.id,
            username=user.username,
            is_new_user=True,
            public_key=None,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth registration failed: {str(e)}",
        )
