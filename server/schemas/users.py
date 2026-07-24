import uuid
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import date, datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="ID пользователя")
    first_name: Optional[str] = Field(..., description="Имя пользователя")
    last_name: Optional[str] = Field(..., description="Фамилия пользователя")
    middle_name: Optional[str] = Field(..., description="Отчество пользователя")
    birth_date: Optional[date] = Field(..., description="Дата рождения пользователя")
    avatar: Optional[str] = Field(..., description="Аватарка пользователя")
    last_seen_at: Optional[datetime] = Field(None, description="Последняя активность (UTC)")

class searchQuery(BaseModel):
    service_id: str
    query: str