from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, UUID, ForeignKey

from server.database.BaseModel import BaseModel


class MobileAppReleases(BaseModel):
    """Загруженные сборки мобильного приложения и метаданные обновлений."""

    __tablename__ = "mobile_app_releases"

    platform = Column(String(32), nullable=False, index=True)  # android | ios | macos | windows
    version = Column(String(32), nullable=False, index=True)  # e.g. 0.5.0
    description = Column(Text, nullable=True)

    original_filename = Column(String(512), nullable=False, default="app-release.bin")
    content_type = Column(String(255), nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False, default=0)
    file_path = Column(Text, nullable=False)  # абсолютный путь на сервере

    # Политика обновления
    min_supported_version = Column(String(32), nullable=True)
    force_update = Column(Boolean, nullable=False, default=False)
    remind_after_hours = Column(Integer, nullable=False, default=24)

    is_latest = Column(Boolean, nullable=False, default=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<MobileAppRelease(id={self.id}, platform={self.platform}, version={self.version}, latest={self.is_latest})>"

