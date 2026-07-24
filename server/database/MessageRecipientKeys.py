"""
Ключи расшифровки сообщений по пользователям.
Одно сообщение (encrypted_data + nonce) в messages, по одной записи на каждого читателя:
encrypted_aes_key зашифрован публичным ключом user_id. Масштабируется на групповые чаты.
"""
from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, ForeignKey, UniqueConstraint, UUID
import uuid


class MessageRecipientKeys(BaseModel):
    __tablename__ = "message_recipient_keys"

    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    encrypted_aes_key = Column(Text, nullable=False)  # Base64, зашифровано публичным ключом user_id

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_message_recipient_keys_message_user"),)

    def __repr__(self):
        return f"<MessageRecipientKey(message_id={self.message_id}, user_id={self.user_id})>"
