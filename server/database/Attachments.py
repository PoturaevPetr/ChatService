from sqlalchemy import Column, String, Integer, ForeignKey, UUID, LargeBinary, Text

from server.database.BaseModel import BaseModel


class Attachments(BaseModel):
    """Зашифрованное вложение (ciphertext только; ключи — внутри зашифрованного сообщения)."""

    __tablename__ = "attachments"

    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    variant = Column(String(20), nullable=False)  # full | thumb
    parent_attachment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    original_filename = Column(String(512), nullable=False, default="file")
    content_type = Column(String(255), nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False, default=0)
    ciphertext = Column(LargeBinary, nullable=False)

    transcription_text = Column(Text, nullable=True)
    transcription_status = Column(String(20), nullable=True)  # pending | done | failed
    transcription_error = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Attachment(id={self.id}, room={self.room_id}, variant={self.variant})>"
