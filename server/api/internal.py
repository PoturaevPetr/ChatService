"""
Внутренние endpoint'ы (MeetService → Novu и т.п.).
Доставка сообщений — только RabbitMQ → Redis node channel (не через HTTP).
"""
import logging
from typing import Literal, Optional

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.database import get_db
from server.database.Users import Users
from server.services import novu_service
from server.services.message_service import _user_push_sender_name
from server.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal", tags=["Internal"])


class MeetCallPushBody(BaseModel):
    callee_id: uuid.UUID
    caller_id: uuid.UUID
    kind: Literal["incoming", "missed"]
    media: Literal["audio", "video"] = "audio"


def verify_internal_secret(x_internal_secret: Optional[str] = Header(None, alias="X-Internal-Secret")):
    if not settings.INTERNAL_DELIVERY_SECRET:
        return
    if x_internal_secret != settings.INTERNAL_DELIVERY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing internal secret",
        )


@router.post("/meet-call-push", status_code=status.HTTP_204_NO_CONTENT)
async def meet_call_push(
    body: MeetCallPushBody,
    _: None = Depends(verify_internal_secret),
    db: Session = Depends(get_db),
):
    """
    MeetService → Novu: «Входящий звонок» / «Пропущенный звонок».
    """
    if not novu_service.is_novu_configured():
        logger.debug("meet-call-push: Novu не настроен (NOVU_SECRET_KEY), пропуск")
        return
    caller_row = db.query(Users).filter(Users.id == body.caller_id).first()
    sender_label = _user_push_sender_name(caller_row) or "Контакт"
    if body.kind == "incoming":
        type_message = "Входящий видеозвонок" if body.media == "video" else "Входящий звонок"
    else:
        type_message = "Пропущенный видеозвонок" if body.media == "video" else "Пропущенный звонок"
    await novu_service.trigger_new_message_push(
        str(body.callee_id),
        message_id=f"meet-{uuid.uuid4()}",
        room_id=None,
        sender_display_name=sender_label,
        type_message=type_message,
    )
    logger.info(
        "meet-call-push Novu: kind=%s callee=%s caller=%s",
        body.kind,
        str(body.callee_id)[:8],
        str(body.caller_id)[:8],
    )
