"""Per-user read state for group-style messages (one messages row, recipient_id NULL)."""

from server.database.BaseModel import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint, UUID
from datetime import datetime
import uuid


class MessageReads(BaseModel):
    __tablename__ = "message_reads"

    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_reads_message_user"),)

    def __repr__(self):
        return f"<MessageRead(message_id={self.message_id}, user_id={self.user_id})>"
