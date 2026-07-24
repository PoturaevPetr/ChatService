from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
import logging
from sqlalchemy.orm import Session, Query
from sqlalchemy import desc
from sqlalchemy import func
from server.database.Rooms import Rooms
from server.database.Users import Users
from server.database.RoomUsers import RoomUsers
from server.database.Messages import Messages
from server.services.message_service import message_service

logger = logging.getLogger(__name__)


class RoomService:
    """Сервис для работы с пользователями"""

    @staticmethod
    def _find_direct_room(db: Session, user_a: uuid.UUID, user_b: uuid.UUID) -> Optional[Rooms]:
        """
        Найти существующую 1-1 комнату между двумя пользователями.
        Используем room_type='direct' и ровно 2 участника.
        """
        users = [user_a, user_b]
        q = (
            db.query(Rooms)
            .join(RoomUsers, Rooms.id == RoomUsers.room_id)
            .filter(Rooms.is_active == True)
            .filter(Rooms.room_type == "direct")
            .filter(RoomUsers.user_id.in_(users))
            .group_by(Rooms.id)
            .having(func.count(func.distinct(RoomUsers.user_id)) == 2)
            .having(func.count(RoomUsers.user_id) == 2)
            .order_by(desc(Rooms.updated_at))
        )
        return q.first()

    @staticmethod
    async def get_or_create_direct_room(db: Session, user_a: uuid.UUID, user_b: uuid.UUID) -> Rooms:
        """
        Гарантировать наличие 1-1 комнаты (room_type='direct') между user_a и user_b.
        Возвращает существующую или создаёт новую.
        """
        existing = RoomService._find_direct_room(db, user_a, user_b)
        if existing:
            return existing
        room = Rooms()
        room.name = "direct"
        room.room_type = "direct"
        room.created_by = user_a
        room.participant_count = 2
        db.add(room)
        db.commit()
        db.refresh(room)

        for _id in [user_a, user_b]:
            user_room = RoomUsers()
            user_room.user_id = _id
            user_room.room_id = room.id
            db.add(user_room)
        db.commit()
        db.refresh(room)
        return room

    @staticmethod
    async def create_room(db: Session, user_id: uuid.UUID, current_user_id: uuid.UUID) -> Rooms:
        """Создать или вернуть существующий личный чат (direct) с user_id."""
        return await RoomService.get_or_create_direct_room(db, current_user_id, user_id)

    @staticmethod
    async def create_group_room(
        db: Session,
        creator_id: uuid.UUID,
        name: str,
        description: Optional[str],
        member_user_ids: List[uuid.UUID],
        avatar: Optional[str] = None,
    ) -> Rooms:
        """
        Новая групповая комната: создатель + member_user_ids (остальные участники, без дубликатов).
        """
        name_clean = (name or "").strip()
        if not name_clean:
            raise ValueError("Group name is required")

        others_ordered = list(dict.fromkeys(uid for uid in member_user_ids if uid != creator_id))
        if not others_ordered:
            raise ValueError("At least one other member is required")

        member_ids: List[uuid.UUID] = [creator_id] + others_ordered
        for uid in member_ids:
            u = db.query(Users).filter(Users.id == uid, Users.is_active == True).first()
            if not u:
                raise ValueError(f"User not found or inactive: {uid}")

        room = Rooms()
        room.name = name_clean
        desc = (description or "").strip()
        room.description = desc if desc else None
        room.room_type = "group"
        room.created_by = creator_id
        room.participant_count = len(member_ids)
        av = (avatar or "").strip()
        room.avatar = av if av else None
        db.add(room)
        db.commit()
        db.refresh(room)

        for uid in member_ids:
            user_room = RoomUsers()
            user_room.user_id = uid
            user_room.room_id = room.id
            user_room.role = "admin" if uid == creator_id else "member"
            db.add(user_room)
        db.commit()
        db.refresh(room)
        return room

    @staticmethod
    def _membership(db: Session, room_id: uuid.UUID, user_id: uuid.UUID) -> Optional[RoomUsers]:
        return (
            db.query(RoomUsers)
            .filter(RoomUsers.room_id == room_id, RoomUsers.user_id == user_id)
            .first()
        )

    @staticmethod
    async def update_group_room(
        db: Session,
        room_id: uuid.UUID,
        actor_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        avatar: Optional[str] = None,
    ) -> Rooms:
        """Обновить поля группы. Только участник с ролью admin."""
        room = db.query(Rooms).filter(Rooms.id == room_id, Rooms.is_active == True).first()
        if not room or room.room_type != "group":
            raise ValueError("Group room not found")

        mem = RoomService._membership(db, room_id, actor_id)
        if not mem or mem.role != "admin":
            raise PermissionError("Only group administrators can update the room")

        if name is not None:
            nc = name.strip()
            if not nc:
                raise ValueError("name must not be empty")
            room.name = nc
        if description is not None:
            d = description.strip()
            room.description = d if d else None
        if avatar is not None:
            av = avatar.strip()
            room.avatar = av if av else None

        db.commit()
        db.refresh(room)
        return room

    @staticmethod
    async def remove_group_member(
        db: Session,
        room_id: uuid.UUID,
        actor_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> List[uuid.UUID]:
        """
        Исключить участника из группы. Возвращает список user_id для WS-уведомления (остальные + исключённый).
        Правила: только admin; нельзя исключить себя (используйте leave); нельзя исключить создателя;
        админа (кроме создателя) может исключить только создатель комнаты.
        """
        if target_user_id == actor_id:
            raise ValueError("Use leave endpoint to leave the group yourself")

        room = db.query(Rooms).filter(Rooms.id == room_id, Rooms.is_active == True).first()
        if not room or room.room_type != "group":
            raise ValueError("Group room not found")

        actor_mem = RoomService._membership(db, room_id, actor_id)
        if not actor_mem or actor_mem.role != "admin":
            raise PermissionError("Only group administrators can remove members")

        if target_user_id == room.created_by:
            raise PermissionError("Cannot remove the group creator")

        target_mem = RoomService._membership(db, room_id, target_user_id)
        if not target_mem:
            raise ValueError("User is not a member of this room")

        if target_mem.role == "admin" and actor_id != room.created_by:
            raise PermissionError("Only the group creator can remove another administrator")

        db.delete(target_mem)
        db.flush()
        remaining = db.query(RoomUsers).filter(RoomUsers.room_id == room_id).count()
        room.participant_count = remaining
        db.commit()

        notify_ids = [
            r[0]
            for r in db.query(RoomUsers.user_id).filter(RoomUsers.room_id == room_id).all()
        ]
        notify_ids.append(target_user_id)
        return list(dict.fromkeys(notify_ids))

    @staticmethod
    async def delete_room_for_user(db: Session, room_id: uuid.UUID, current_user_id: uuid.UUID) -> bool:
        """
        "Удалить чат" для текущего пользователя: убрать его из room_user,
        чтобы комната исчезла из GET /rooms для этого пользователя.
        Комната и сообщения у других участников остаются.
        """
        membership = db.query(RoomUsers).filter(
            RoomUsers.room_id == room_id,
            RoomUsers.user_id == current_user_id,
        ).first()
        if not membership:
            return False

        db.delete(membership)
        db.flush()

        remaining = db.query(RoomUsers).filter(RoomUsers.room_id == room_id).count()
        room = db.query(Rooms).filter(Rooms.id == room_id).first()
        if room:
            room.participant_count = remaining
            if remaining <= 0:
                room.is_active = False
        db.commit()
        return True

    @staticmethod
    async def delete_room_for_all(db: Session, room_id: uuid.UUID, current_user_id: uuid.UUID) -> bool:
        """
        Удалить чат полностью (для обоих участников):
        - удалить сообщения в комнате
        - убрать всех участников из room_user
        - отключить комнату (is_active=False)
        """
        membership = db.query(RoomUsers).filter(
            RoomUsers.room_id == room_id,
            RoomUsers.user_id == current_user_id,
        ).first()
        if not membership:
            return False

        room = db.query(Rooms).filter(Rooms.id == room_id).first()
        if room and room.room_type == "group" and room.created_by != current_user_id:
            return False

        # Удаляем сообщения
        db.query(Messages).filter(Messages.room_id == room_id).delete(synchronize_session=False)
        # Удаляем связи участников
        db.query(RoomUsers).filter(RoomUsers.room_id == room_id).delete(synchronize_session=False)

        room = db.query(Rooms).filter(Rooms.id == room_id).first()
        if room:
            room.participant_count = 0
            room.is_active = False

        db.commit()
        return True

    
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
    def get_last_message_per_room(
        db: Session,
        room_ids: List[uuid.UUID],
        current_user_id: uuid.UUID,
        device_id: Optional[str] = None,
    ) -> Dict[uuid.UUID, dict]:
        """
        Для каждого room_id возвращает последнее сообщение (по sent_at),
        с ключом расшифровки для current_user_id. Возвращает dict: room_id -> RoomLastMessage-подобный dict.
        """
        if not room_ids:
            return {}
        last_messages = (
            db.query(Messages)
            .filter(Messages.room_id.in_(room_ids))
            .order_by(desc(Messages.sent_at))
            .all()
        )
        by_room: Dict[uuid.UUID, Messages] = {}
        for m in last_messages:
            if m.room_id and m.room_id not in by_room:
                by_room[m.room_id] = m
        result = {}
        for room_id, msg in by_room.items():
            enc_key, device_envelopes = message_service.resolve_decrypt_material_for_user(
                msg.id, current_user_id, db, device_id=device_id
            )
            if enc_key is None:
                continue
            result[room_id] = {
                "message_id": msg.id,
                "sender_id": msg.sender_id,
                "recipient_id": msg.recipient_id,
                "room_id": msg.room_id,
                "encrypted_data": msg.encrypted_data,
                "encrypted_aes_key": enc_key,
                "nonce": msg.nonce,
                "sent_at": msg.sent_at,
                "is_read": message_service.is_read_for_viewer(msg, current_user_id, db),
                "device_envelopes": device_envelopes or None,
            }
        return result


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