"""Реакции на сообщения: только из фиксированного набора эмодзи."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from server.database.Messages import Messages
from server.database.MessageReactions import MessageReactions
from server.database.RoomUsers import RoomUsers


# 20 эмодзи (разные эмоции) + обязательное сердце ❤️
REACTION_EMOJI_ALLOWLIST = frozenset(
    {
        "❤️",
        "😂",
        "😮",
        "😢",
        "🙏",
        "👍",
        "👎",
        "🔥",
        "✨",
        "😍",
        "🤔",
        "😭",
        "💯",
        "🎉",
        "😊",
        "😡",
        "🤣",
        "👀",
        "💪",
        "🙌",
    }
)


class ReactionService:
    @staticmethod
    def _room_member_ids(db: Session, room_id: uuid.UUID) -> frozenset:
        rows = db.query(RoomUsers.user_id).filter(RoomUsers.room_id == room_id).all()
        return frozenset(r[0] for r in rows)

    @staticmethod
    def set_reaction(
        db: Session,
        *,
        user_id: uuid.UUID,
        message_id: uuid.UUID,
        emoji: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Поставить или сменить реакцию. Повторный клик по тому же эмодзи — снять реакцию.
        Возвращает ("ok", payload) или ("error", {"detail": str}).
        """
        if emoji not in REACTION_EMOJI_ALLOWLIST:
            return "error", {"detail": "Emoji not allowed"}

        msg = db.query(Messages).filter(Messages.id == message_id).first()
        if not msg or msg.room_id is None:
            return "error", {"detail": "Message not found"}

        room_id: uuid.UUID = msg.room_id
        members = ReactionService._room_member_ids(db, room_id)
        if user_id not in members:
            return "error", {"detail": "Not a room member"}

        existing = (
            db.query(MessageReactions)
            .filter(
                MessageReactions.message_id == message_id,
                MessageReactions.user_id == user_id,
            )
            .first()
        )

        removed = False
        if existing:
            if existing.emoji == emoji:
                db.delete(existing)
                db.commit()
                removed = True
            else:
                existing.emoji = emoji
                db.commit()
        else:
            db.add(
                MessageReactions(
                    message_id=message_id,
                    room_id=room_id,
                    user_id=user_id,
                    emoji=emoji,
                )
            )
            db.commit()

        notify_ids = list(members)
        return "ok", {
            "room_id": room_id,
            "message_id": message_id,
            "user_id": user_id,
            "emoji": emoji,
            "removed": removed,
            "notify_user_ids": notify_ids,
            "message_sender_id": msg.sender_id,
        }

    @staticmethod
    def batch_for_messages(
        db: Session,
        *,
        room_id: uuid.UUID,
        user_id: uuid.UUID,
        message_ids: List[uuid.UUID],
    ) -> Dict[str, List[Dict[str, str]]]:
        """Список реакций по message_id (только сообщения этой комнаты)."""
        if not message_ids:
            return {}
        if user_id not in ReactionService._room_member_ids(db, room_id):
            return {}

        mids = list({mid for mid in message_ids})
        rows = (
            db.query(MessageReactions)
            .join(Messages, Messages.id == MessageReactions.message_id)
            .filter(
                Messages.room_id == room_id,
                MessageReactions.message_id.in_(mids),
            )
            .all()
        )
        out: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            key = str(r.message_id)
            out.setdefault(key, []).append(
                {
                    "user_id": str(r.user_id),
                    "emoji": r.emoji,
                }
            )
        for k in out:
            out[k].sort(key=lambda x: (x["emoji"], x["user_id"]))
        return out


reaction_service = ReactionService()
