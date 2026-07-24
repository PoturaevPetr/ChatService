from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, DateTime, ForeignKey, UUID, Integer, Boolean, UniqueConstraint
from datetime import datetime, timezone


class Devices(BaseModel):
    """Клиентское устройство пользователя (per-device identity). CRYPTO_DEVICES_V3."""

    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_devices_user_device"),
    )

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Стабильный id, сгенерированный на клиенте (uuid string)
    device_id = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    platform = Column(String(32), nullable=False, default="web")  # web | ios | android | desktop

    # Identity public (PEM SPKI или base64 — клиент шлёт PEM)
    identity_key_public = Column(Text, nullable=False)
    # Curve25519 public (base64) for signal_v1; optional until device upgrades
    signal_identity_key_public = Column(Text, nullable=True)
    registration_id = Column(Integer, nullable=False, default=0)

    signed_prekey_id = Column(Integer, nullable=True)
    signed_prekey_public = Column(Text, nullable=True)
    signed_prekey_signature = Column(Text, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    # V3.3: set when device completed link/finish (or first device of account)
    linked_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Devices(user={self.user_id}, device_id={self.device_id})>"


class DeviceOneTimePrekeys(BaseModel):
    """One-time prekeys для X3DH (V3.2+); V3.1 — upload/consume API уже есть."""

    __tablename__ = "device_one_time_prekeys"
    __table_args__ = (
        UniqueConstraint("device_row_id", "key_id", name="uq_otpk_device_key_id"),
    )

    device_row_id = Column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key_id = Column(Integer, nullable=False)
    public_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    consumed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<DeviceOTPK(device={self.device_row_id}, key_id={self.key_id})>"
