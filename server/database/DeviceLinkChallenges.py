"""V3.3: QR/code linking challenges between devices of the same user."""

from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, DateTime, ForeignKey, UUID, UniqueConstraint
from datetime import datetime, timezone


class DeviceLinkChallenges(BaseModel):
    __tablename__ = "device_link_challenges"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(16), nullable=False, index=True)
    created_by_device_id = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    consumed_by_device_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<DeviceLinkChallenge(user={self.user_id}, code={self.code})>"
