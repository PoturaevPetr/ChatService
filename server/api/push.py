"""
Регистрация FCM-токена мобильного клиента → Novu subscriber credentials.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from server.auth.middleware import get_current_jwt_user
from server.services import novu_service

router = APIRouter(prefix="/api/v1/push", tags=["Push"])


class PushRegisterBody(BaseModel):
    token: str = Field(..., min_length=10, description="FCM device token")
    platform: str = Field(default="android", description="android | ios | web")


class PushRegisterResponse(BaseModel):
    ok: bool
    novu_updated: bool
    skipped: bool = False
    detail: Optional[str] = None


@router.post("/register", response_model=PushRegisterResponse)
async def register_push_device(
    body: PushRegisterBody,
    current_user: dict = Depends(get_current_jwt_user),
):
    """
    Привязать FCM-токен устройства к текущему пользователю в Novu (subscriberId = user_id).
    Пока провайдер FCM в Novu настроен под Android; для iOS позже можно расширить (APNs).
    """
    if not novu_service.is_novu_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push backend (Novu) is not configured",
        )

    plat = (body.platform or "").lower().strip()
    if plat != "android":
        return PushRegisterResponse(
            ok=True,
            novu_updated=False,
            skipped=True,
            detail="FCM registration is only forwarded to Novu for Android in this build",
        )

    subscriber_id = str(current_user["user_id"])
    updated, novu_hint = await novu_service.upsert_fcm_device_tokens(
        subscriber_id, [body.token.strip()]
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=novu_hint
            or "Failed to register device token with notification provider",
        )

    return PushRegisterResponse(ok=True, novu_updated=True)
