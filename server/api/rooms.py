from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status, Query, Path
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from server.database import get_db
from server.database.Messages import Messages
from server.database.UserKeys import UserKeys
from server.database.Users import Users
from server.auth.middleware import get_current_user
from server.services.room_services import room_service
from sqlalchemy.orm import Session
from datetime import date
from server.schemas import (
    RoomResponce,
    RequestCreateRoom
)

router = APIRouter(prefix="/api/v1/rooms", tags=["Rooms"])

@router.post("/", response_model=RoomResponce)
async def create_room(
    request: RequestCreateRoom,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    print(current_user)
    room = await room_service.create_room(
        db=db,
        user_id=request.user_id,
        current_user_id=current_user.get("user_id")
    )
    return room

@router.get("/", response_model=list[RoomResponce])
async def get_rooms_list(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rooms = await room_service.rooms_user(db, current_user)  
    return rooms
