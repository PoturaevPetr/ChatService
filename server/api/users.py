from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status, Query, Path

from datetime import datetime
import uuid

from server.database import get_db
from server.database.Messages import Messages
from server.database.Users import Users
from server.auth.middleware import get_current_user
from server.services.users_services import users_service
from sqlalchemy.orm import Session
from server.schemas import (
    UserResponse,
    searchQuery
)


router = APIRouter(prefix="/api/v1/users", tags=["Users"])



@router.get("/list", response_model=List[UserResponse])
async def get_messages(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить список доступных пользователей для текущего пользователя

    Для polling клиентов без WebSocket
    """
    users: list[Users] = await users_service.get_users(db=db)
    return users

@router.post("/search", response_model=List[UserResponse])
async def get_search_users(
    request: searchQuery,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    print(request.service_id, request.query)
    users = await users_service.search_users(
        db=db,
        service_id=request.service_id,
        query=request.query
    )
    return users


@router.get("/{user_id}", response_model=UserResponse)
async def get_article(
    user_id: uuid.UUID = Path(..., description="ID пользователя"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить статью по ID"""
    user = await users_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")


    return user