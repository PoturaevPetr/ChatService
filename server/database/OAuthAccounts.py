from server.database.BaseModel import BaseModel
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, UUID
from sqlalchemy.orm import relationship
from datetime import datetime


class OAuthAccounts(BaseModel):
    """Привязка внешнего аккаунта (Google / Яндекс / VK) к пользователю чата."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_subject"),)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(32), nullable=False, index=True)
    provider_user_id = Column(String(255), nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("Users", backref="oauth_accounts")
