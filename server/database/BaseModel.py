from server.database import Base
from sqlalchemy import Column, DateTime, UUID
import uuid


class BaseModel(Base):
    __abstract__ = True
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_date = Column(DateTime(timezone=True))