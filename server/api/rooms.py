from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, status, Query, Path, Header
from pydantic import BaseModel, Field
from datetime import datetime
import uuid
from sqlalchemy import func, exists

from server.database import get_db
from server.database.Messages import Messages
from server.database.MessageRecipientKeys import MessageRecipientKeys
from server.database.MessageReads import MessageReads
from server.database.Users import Users
from server.database.RoomUsers import RoomUsers
from server.database.Rooms import Rooms
from server.auth.middleware import get_current_user
from server.services.room_services import room_service
from sqlalchemy.orm import Session
from datetime import date
from server.websocket.manager import manager
from server.schemas import (
    RoomResponce,
    RoomLastMessage,
    RequestCreateRoom,
)
from server.schemas.rooms import RoomUserResponse, PatchGroupRoomRequest, PatchRoomMeRequest


def _serialize_room(
    db: Session,
    room: Rooms,
    last_msg: dict | None,
    unread_count: int,
    notifications_enabled: bool = True,
) -> RoomResponce:
    rows = (
        db.query(Users, RoomUsers.role)
        .join(RoomUsers, RoomUsers.user_id == Users.id)
        .filter(RoomUsers.room_id == room.id)
        .all()
    )
    users_list = [
        RoomUserResponse(
            id=u.id,
            first_name=u.first_name,
            last_name=u.last_name,
            middle_name=u.middle_name,
            birth_date=u.birth_date,
            avatar=u.avatar,
            last_seen_at=u.last_seen_at,
            role=(role or "member"),
        )
        for u, role in rows
    ]
    return RoomResponce(
        id=room.id,
        name=room.name or "",
        description=room.description or "",
        created_at=room.created_at,
        created_by=room.created_by,
        room_type=room.room_type or "group",
        avatar=room.avatar,
        users=users_list,
        last_message=RoomLastMessage(**last_msg) if last_msg else None,
        unread_count=unread_count,
        notifications_enabled=notifications_enabled,
    )


router = APIRouter(prefix="/api/v1/rooms", tags=["Rooms"])


@router.post("/", response_model=RoomResponce)
async def create_room(
    request: RequestCreateRoom,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user_id = current_user.get("user_id")
    try:
        if request.member_user_ids:
            room = await room_service.create_group_room(
                db=db,
                creator_id=current_user_id,
                name=request.name or "",
                description=request.description,
                member_user_ids=request.member_user_ids,
                avatar=request.avatar,
            )
        else:
            room = await room_service.create_room(
                db=db,
                user_id=request.user_id,
                current_user_id=current_user_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return _serialize_room(db, room, None, 0)


@router.patch("/{room_id}", response_model=RoomResponce)
async def patch_group_room(
    room_id: uuid.UUID,
    body: PatchGroupRoomRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Обновить группу (название, описание, аватар). Только администратор комнаты."""
    if body.name is None and body.description is None and body.avatar is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    try:
        room = await room_service.update_group_room(
            db=db,
            room_id=room_id,
            actor_id=current_user["user_id"],
            name=body.name,
            description=body.description,
            avatar=body.avatar,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    last_messages = room_service.get_last_message_per_room(db, [room.id], current_user["user_id"])
    last_msg = last_messages.get(room.id)
    for ru in db.query(RoomUsers.user_id).filter(RoomUsers.room_id == room_id).all():
        await manager.send_to_user(
            ru[0],
            {"type": "room_updated", "data": {"room_id": str(room_id)}},
        )
    return _serialize_room(db, room, last_msg, 0, notifications_enabled=True)


@router.patch("/{room_id}/me", response_model=RoomResponce)
async def patch_room_me(
    room_id: uuid.UUID,
    body: PatchRoomMeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
):
    """Настройки текущего пользователя в комнате (уведомления и т.д.)."""
    if body.notifications_enabled is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    uid = current_user["user_id"]
    row = (
        db.query(RoomUsers)
        .filter(RoomUsers.room_id == room_id, RoomUsers.user_id == uid)
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found or not a member")
    row.notifications_enabled = bool(body.notifications_enabled)
    db.commit()
    db.refresh(row)
    room = db.query(Rooms).filter(Rooms.id == room_id, Rooms.is_active == True).first()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    last_messages = room_service.get_last_message_per_room(
        db, [room.id], uid, device_id=x_device_id
    )
    last_msg = last_messages.get(room.id)
    return _serialize_room(
        db,
        room,
        last_msg,
        0,
        notifications_enabled=bool(row.notifications_enabled),
    )


@router.post("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Покинуть комнату (удаляет только вашу связь room_user)."""
    ok = await room_service.delete_room_for_user(db, room_id, current_user["user_id"])
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found or not a member")
    return None


@router.delete("/{room_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_room_member(
    room_id: uuid.UUID,
    member_user_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Исключить участника из группы (только администратор).
    Создателя исключить нельзя; другого админа может исключить только создатель.
    """
    try:
        notify_ids = await room_service.remove_group_member(
            db=db,
            room_id=room_id,
            actor_id=current_user["user_id"],
            target_user_id=member_user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    payload = {
        "type": "room_member_removed",
        "data": {"room_id": str(room_id), "user_id": str(member_user_id)},
    }
    for uid in notify_ids:
        await manager.send_to_user(uid, payload)
    return None


@router.get("/", response_model=list[RoomResponce])
async def get_rooms_list(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
):
    rooms = await room_service.rooms_user(db, current_user)
    if not rooms:
        return []
    room_ids = [r.id for r in rooms]
    last_messages = room_service.get_last_message_per_room(
        db, room_ids, current_user["user_id"], device_id=x_device_id
    )

    # Непрочитанные: (1) личные входящие — recipient_id=я, is_read=False;
    # (2) группа (вариант A) — одна строка messages, recipient_id NULL, есть мой ключ в message_recipient_keys,
    #     нет строки в message_reads.
    uid = current_user["user_id"]
    unread_rows = (
        db.query(Messages.room_id, func.count(Messages.id))
        .filter(Messages.room_id.in_(room_ids))
        .filter(Messages.recipient_id == uid)
        .filter(Messages.is_read == False)
        .filter(Messages.sender_id != uid)
        .group_by(Messages.room_id)
        .all()
    )
    not_read = ~exists().where(
        MessageReads.message_id == Messages.id,
        MessageReads.user_id == uid,
    )
    group_unread_rows = (
        db.query(Messages.room_id, func.count(Messages.id))
        .join(
            MessageRecipientKeys,
            (MessageRecipientKeys.message_id == Messages.id)
            & (MessageRecipientKeys.user_id == uid),
        )
        .filter(Messages.room_id.in_(room_ids))
        .filter(Messages.recipient_id.is_(None))
        .filter(Messages.sender_id != uid)
        .filter(not_read)
        .group_by(Messages.room_id)
        .all()
    )
    unread_by_room: dict[uuid.UUID, int] = {rid: 0 for rid in room_ids}
    for rid, cnt in unread_rows:
        unread_by_room[rid] = int(cnt)
    for rid, cnt in group_unread_rows:
        unread_by_room[rid] = unread_by_room.get(rid, 0) + int(cnt)
    pref_rows = (
        db.query(RoomUsers.room_id, RoomUsers.notifications_enabled)
        .filter(RoomUsers.user_id == uid, RoomUsers.room_id.in_(room_ids))
        .all()
    )
    notifications_by_room: dict[uuid.UUID, bool] = {
        rid: True if enabled is None else bool(enabled) for rid, enabled in pref_rows
    }
    result = []
    for room in rooms:
        last_msg = last_messages.get(room.id)
        result.append(
            _serialize_room(
                db,
                room,
                last_msg,
                unread_by_room.get(room.id, 0),
                notifications_enabled=notifications_by_room.get(room.id, True),
            )
        )
    return result


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room_for_me(
    room_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Удалить чат для обоих участников: удалить сообщения и деактивировать комнату.
    """
    # Collect participants before deletion so we can notify them in realtime.
    participant_ids = [
        ru.user_id
        for ru in db.query(RoomUsers.user_id).filter(RoomUsers.room_id == room_id).all()
    ]

    ok = await room_service.delete_room_for_all(db, room_id, current_user.get("user_id"))
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    # Notify both participants over WebSocket (only online on this worker).
    notification = {"type": "room_deleted", "data": {"room_id": str(room_id)}}
    for uid in participant_ids:
        await manager.send_to_user(uid, notification)
    return None
