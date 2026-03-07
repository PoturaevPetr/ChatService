from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import uuid
from jose import jwt, JWTError

from server.database import get_db
from server.database.Users import Users
from server.database.UserKeys import UserKeys
from server.database.Sessions import Sessions
from server.auth.jwt_handler import jwt_handler
from server.auth.middleware import get_current_user
from server.crypto.key_manager import KeyManager
from sqlalchemy.orm import Session
from datetime import date

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


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


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    public_key: str
    private_key: str  # Возвращается только при регистрации
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

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Регистрация нового пользователя с генерацией ключевой пары

    - **username**: Уникальное имя пользователя
    - **service_id**: Идентификатор сервиса-клиента
    """
    # Проверяем, не существует ли пользователь
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
        # Создаем пользователя
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
        db.flush()  # Получаем user_id

        # Генерируем ключевую пару
        keypair_data = KeyManager.generate_user_keypair(str(user.id))

        # Сохраняем ключи в БД
        user_key = UserKeys(
            user_id=user.id,
            public_key=keypair_data["public_key"],
            private_key_encrypted=keypair_data["private_key"],  # В продакшене зашифровать паролем!
            key_type=keypair_data["key_type"],
            key_fingerprint=KeyManager.export_public_key(keypair_data["public_key"], format="fingerprint"),
            is_active=True
        )
        db.add(user_key)

        # Создаем JWT токены
        access_token = jwt_handler.create_access_token(user.id, request.service_id)
        refresh_token = jwt_handler.create_refresh_token(user.id, request.service_id)

        # Создаем сессию
        session = Sessions(
            user_id=user.id,
            token_jti=jwt_handler.decode_token(access_token)["jti"],
            refresh_token=refresh_token,
            service_id=request.service_id,
            expires_at=datetime.utcnow() + timedelta(minutes=jwt_handler.access_token_expire_minutes)
        )
        db.add(session)
        db.commit()

        return RegisterResponse(
            user_id=user.id,
            username=user.username,
            public_key=keypair_data["public_key"],
            private_key=keypair_data["private_key"],  # Только при регистрации!
            access_token=access_token,
            refresh_token=refresh_token
        )

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
    user.first_name = request.first_name
    user.middle_name = request.middle_name
    user.last_name = request.last_name
    user.avatar = request.avatar
    user.birth_date = request.birth_date
    db.commit()
    db.refresh(user)
    return user

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

    # Создаем токены
    access_token = jwt_handler.create_access_token(user.id, request.service_id)
    refresh_token = jwt_handler.create_refresh_token(user.id, request.service_id)

    # Обновляем last_login
    user.last_login = datetime.utcnow()

    # Создаем сессию
    session = Sessions(
        user_id=user.id,
        token_jti=jwt_handler.decode_token(access_token)["jti"],
        refresh_token=refresh_token,
        service_id=request.service_id,
        expires_at=datetime.utcnow() + timedelta(minutes=jwt_handler.access_token_expire_minutes)
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
        payload = jwt_handler.verify_token(request.refresh_token, "refresh")
        user_id = uuid.UUID(payload["sub"])
        service_id = payload["service_id"]

        # Проверяем сессию
        session = db.query(Sessions).filter(
            Sessions.refresh_token == request.refresh_token,
            Sessions.user_id == user_id
        ).first()

        if not session or not session.is_valid():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

        # Создаем новые токены
        new_access_token = jwt_handler.create_access_token(user_id, service_id)
        new_refresh_token = jwt_handler.create_refresh_token(user_id, service_id)

        # Обновляем сессию
        session.refresh_token = new_refresh_token
        session.expires_at = datetime.utcnow() + timedelta(minutes=jwt_handler.access_token_expire_minutes)

        db.commit()

        return RefreshTokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
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
