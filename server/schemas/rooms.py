import uuid
from pydantic import BaseModel, Field, model_validator, ConfigDict
from typing import Optional, List
from datetime import date, datetime


class UserResponse(BaseModel):
    id: uuid.UUID = Field(..., description="ID пользователя")
    first_name: Optional[str] = Field(..., description="Имя пользователя")
    last_name: Optional[str] = Field(..., description="Фамилия пользователя")
    middle_name: Optional[str] = Field(..., description="Отчество пользователя")
    birth_date: Optional[date] = Field(..., description="Дата рождения пользователя")
    avatar: Optional[str] = Field(..., description="Аватарка пользователя")
    last_seen_at: Optional[datetime] = Field(None, description="Последняя активность (UTC)")


class RoomUserResponse(UserResponse):
    """Участник комнаты с ролью (в группе: admin | member | moderator)."""

    role: str = Field("member", description="admin | member | moderator")


class RoomLastMessage(BaseModel):
    """Последнее сообщение комнаты (для превью в списке чатов). Ключ расшифровки — для текущего пользователя."""
    message_id: uuid.UUID
    sender_id: uuid.UUID
    recipient_id: Optional[uuid.UUID]
    room_id: Optional[uuid.UUID]
    encrypted_data: str
    encrypted_aes_key: str
    nonce: str
    sent_at: datetime
    is_read: bool
    device_envelopes: Optional[List[dict]] = None


class RoomResponce(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str] = ""
    created_at: datetime
    created_by: uuid.UUID
    """direct — личный чат; group — группа (одно сообщение на всех, вариант A)."""
    room_type: str = "group"
    avatar: Optional[str] = None
    users: list[RoomUserResponse]
    last_message: Optional[RoomLastMessage] = None
    # Сколько непрочитанных сообщений для текущего пользователя в этой комнате
    unread_count: int = 0
    notifications_enabled: bool = True


class PatchRoomMeRequest(BaseModel):
    """Настройки текущего пользователя в комнате (mute, и т.д.)."""

    notifications_enabled: Optional[bool] = None


class RequestCreateRoom(BaseModel):
    """Создание чата: либо личный (user_id), либо группа (name + member_user_ids)."""

    user_id: Optional[uuid.UUID] = Field(None, description="Собеседник для личного чата (как раньше)")
    name: Optional[str] = Field(None, description="Название группы (обязательно для группы)")
    description: Optional[str] = Field(None, description="Описание группы")
    member_user_ids: Optional[List[uuid.UUID]] = Field(
        None,
        description="Остальные участники группы (без текущего пользователя); создатель добавляется на сервере. Минимум один UUID.",
    )
    avatar: Optional[str] = Field(None, description="Аватар группы (data URL или URL)")

    @model_validator(mode="after")
    def validate_direct_or_group(self):
        has_group = self.member_user_ids is not None and len(self.member_user_ids) > 0
        if has_group:
            if not (self.name or "").strip():
                raise ValueError("name is required when creating a group room")
            return self
        if self.user_id is None:
            raise ValueError("Either user_id (direct chat) or member_user_ids (group) is required")
        return self


class PatchGroupRoomRequest(BaseModel):
    """Обновление группы (только администраторы комнаты). Все поля опциональны — меняются только переданные."""

    name: Optional[str] = None
    description: Optional[str] = None
    avatar: Optional[str] = None