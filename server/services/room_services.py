from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import logging
from sqlalchemy.orm import Session, Query
from server.database.Rooms import Rooms
from server.database.Users import Users
from server.database.RoomUsers import RoomUsers

logger = logging.getLogger(__name__)


class RoomService:
    """Сервис для работы с пользователями"""

    @staticmethod
    async def create_room(db: Session, user_id: uuid.UUID, current_user_id: uuid.UUID) -> Rooms:
        """Получить список пользователей"""
        print(user_id, current_user_id)
        room = Rooms()
        room.name = "room"
        room.created_by = current_user_id
        db.add(room)
        db.commit()
        db.refresh(room)

        users_list = [user_id, current_user_id]
        for _id in users_list:
            user_room = RoomUsers()
            user_room.user_id = _id
            user_room.room_id = room.id
            db.add(user_room)
        db.commit()

        return room

    
    @staticmethod
    async def rooms_user(db: Session, current_user: dict) -> list[Rooms]:
        """
        Получить все комнаты пользователя через relationship
        """
        user_id = current_user.get("user_id")
        
        # Получаем пользователя с загруженными связями
        user = db.query(Users).filter(Users.id == user_id).first()
        if not user:
            return []
        
        # Через rooms_relations получаем комнаты
        rooms = []
        for room_user in user.rooms_relations:
            if room_user.room and room_user.room.is_active:
                rooms.append(room_user.room)
        
        return rooms


    @staticmethod
    async def rooms_user_with_details(db: Session, current_user: dict) -> list[dict]:
        """
        Получить комнаты пользователя с деталями об участии
        """
        user_id = current_user.get("id")
        
        # Более детальный запрос
        results = (
            db.query(
                Rooms,
                RoomUsers.role,
                RoomUsers.joined_at,
                RoomUsers.is_favorite,
                RoomUsers.last_read_at,
                RoomUsers.notifications_enabled
            )
            .join(RoomUsers, Rooms.id == RoomUsers.room_id)
            .filter(RoomUsers.user_id == user_id)
            .filter(Rooms.is_active == True)
            .order_by(RoomUsers.is_favorite.desc(), Rooms.updated_at.desc())
            .all()
        )
        
        # Форматируем результат
        rooms_list = []
        for room, role, joined_at, is_favorite, last_read_at, notifications_enabled in results:
            # Получаем информацию о создателе
            creator = db.query(Users).get(room.created_by)
            
            rooms_list.append({
                "id": room.id,
                "name": room.name,
                "description": room.description,
                "room_type": room.room_type,
                "participant_count": room.participant_count,
                "created_at": room.created_at,
                "updated_at": room.updated_at,
                "creator": {
                    "id": creator.id if creator else None,
                    "username": creator.username if creator else None,
                    "full_name": f"{creator.first_name or ''} {creator.last_name or ''}".strip() if creator else None
                } if creator else None,
                "user_role": role,
                "joined_at": joined_at,
                "is_favorite": is_favorite,
                "last_read_at": last_read_at,
                "notifications_enabled": notifications_enabled,
                "unread_count": 0  # здесь можно добавить логику подсчета непрочитанных
            })
        
        return rooms_list


    @staticmethod
    async def get_user_rooms_by_type(
        db: Session, 
        current_user: dict,
        room_type: str = None,
        include_inactive: bool = False
    ) -> list[Rooms]:
        """
        Получить комнаты пользователя с фильтром по типу
        """
        user_id = current_user.get("id")
        
        query = (
            db.query(Rooms)
            .join(RoomUsers, Rooms.id == RoomUsers.room_id)
            .filter(RoomUsers.user_id == user_id)
        )
        
        if not include_inactive:
            query = query.filter(Rooms.is_active == True)
        
        if room_type:
            query = query.filter(Rooms.room_type == room_type)
        
        return query.order_by(Rooms.updated_at.desc()).all()


    @staticmethod
    async def check_user_in_room(db: Session, user_id: str, room_id: str) -> bool:
        """
        Проверить, находится ли пользователь в комнате
        """
        return db.query(RoomUsers).filter(
            RoomUsers.user_id == user_id,
            RoomUsers.room_id == room_id
        ).first() is not None


    @staticmethod
    async def get_user_role_in_room(db: Session, user_id: str, room_id: str) -> str:
        """
        Получить роль пользователя в комнате
        """
        room_user = db.query(RoomUsers).filter(
            RoomUsers.user_id == user_id,
            RoomUsers.room_id == room_id
        ).first()
        
        return room_user.role if room_user else None


room_service = RoomService()