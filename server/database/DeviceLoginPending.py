"""Pending desktop/web login: new device shows QR, trusted mobile approves."""

from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, DateTime, ForeignKey, UUID, Text
from datetime import datetime, timezone
import uuid


class DeviceLoginPending(BaseModel):
    __tablename__ = "device_login_pending"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(16), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    # Serialized DeviceRegisterPayload JSON from requesting device
    device_payload_json = Column(Text, nullable=False)

    approved_by_device_id = Column(String(64), nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
