"""
Ключи расшифровки сообщений по устройствам (CRYPTO_DEVICES_V3 hybrid_device_v0).
Одно тело в messages; по одной записи на каждое destination device.
"""
from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, ForeignKey, UniqueConstraint, UUID


class MessageDeviceKeys(BaseModel):
    __tablename__ = "message_device_keys"

    message_id = Column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id = Column(String(64), nullable=False, index=True)
    encrypted_aes_key = Column(Text, nullable=False)  # Base64, RSA-OAEP(device identity)

    __table_args__ = (
        UniqueConstraint("message_id", "device_id", name="uq_message_device_keys_message_device"),
    )

    def __repr__(self):
        return f"<MessageDeviceKey(message_id={self.message_id}, device_id={self.device_id})>"
