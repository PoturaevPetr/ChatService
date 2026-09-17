from server.database.BaseModel import BaseModel
from sqlalchemy import Column, Text, String, DateTime, ForeignKey, UUID, UniqueConstraint
from datetime import datetime
import uuid


class UserDrafts(BaseModel):
    """
    Персистентное хранилище E2E-зашифрованных черновиков сообщений пользователя.
    Черновик зашифрован ключом самого пользователя (Zero-Knowledge).
    """

    __tablename__ = "user_drafts"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encrypted_data = Column(Text, nullable=False)  # AES-256-GCM ciphertext
    nonce = Column(String(64), nullable=False)     # Base64 iv (12 bytes)
    encrypted_aes_key = Column(Text, nullable=False)  # RSA-OAEP wrapped with user's master public key

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "room_id", name="uq_user_drafts_user_room"),
    )

    def __repr__(self):
        return f"<UserDraft(user_id={self.user_id}, room_id={self.room_id})>"
