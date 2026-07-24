from typing import Optional, Any, Dict
from datetime import datetime
import uuid
import logging
import asyncio

import requests

logger = logging.getLogger(__name__)


def _post_mobile_callback_sync(url: str, data: Dict[str, Any]) -> Any:
    """Синхронный POST — вызывать через asyncio.to_thread, чтобы не блокировать event loop."""
    response = requests.post(url, json=data, timeout=5)
    response.raise_for_status()
    if not response.content:
        return {"ok": True}
    return response.json()


class CallbackService:
    @staticmethod
    async def callback_new_message_mis(
        url: str,
        message_id: uuid.UUID,
        sender_id: uuid.UUID,
        recipient_id: uuid.UUID,
        room_id: Optional[uuid.UUID],
        encrypted_data: str,
        sent_at: datetime,
    ):
        data = {
            "message_id": str(message_id),
            "sender_id": str(sender_id),
            "recipient_id": str(recipient_id),
            "room_id": str(room_id) if room_id else None,
            "sent_at": sent_at.isoformat(),
        }
        try:
            return await asyncio.to_thread(_post_mobile_callback_sync, url, data)
        except Exception:
            logger.exception(
                "Mobile callback failed for message %s to %s",
                message_id,
                url,
            )
            raise

