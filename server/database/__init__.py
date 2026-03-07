from sqlalchemy.orm import declarative_base

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from server.settings import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create a shared Base for all models
Base = declarative_base()


def init_db():
    """Инициализация базы данных - создание таблиц"""
    from server.database.Users import Users
    from server.database.UserKeys import UserKeys
    from server.database.Sessions import Sessions
    from server.database.Messages import Messages
    from server.database.Rooms import Rooms
    from server.database.APIKeys import APIKeys
    from server.database.RoomUsers import RoomUsers

    Base.metadata.create_all(bind=engine)
