"""Публичные для клиента настройки (после авторизации)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from server.auth.middleware import get_current_jwt_user
from server.settings import settings

router = APIRouter(prefix="/api/v1/client", tags=["client"])


class MeetServiceConfigResponse(BaseModel):
    """Базовый URL MeetService (без завершающего слэша). Пусто — звонки на стороне сервера отключены."""

    meet_service_url: str | None = Field(
        None,
        description="Origin MeetService, например https://meet.example.com",
    )


@router.get("/meet-service", response_model=MeetServiceConfigResponse)
async def get_meet_service_config(_user: dict = Depends(get_current_jwt_user)) -> MeetServiceConfigResponse:
    raw = (getattr(settings, "MEET_SERVICE_PUBLIC_URL", None) or "").strip()
    if not raw:
        return MeetServiceConfigResponse(meet_service_url=None)
    return MeetServiceConfigResponse(meet_service_url=raw.rstrip("/"))
