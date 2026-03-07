from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import logging

from server.crypto.hybrid import HybridEncryption
from server.database import get_db
from server.database.Messages import Messages
from server.database.Users import Users
from server.database.UserKeys import UserKeys
from server.services.notification_service import NotificationService
from sqlalchemy.orm import Session, Query
from sqlalchemy import or_, and_

logger = logging.getLogger(__name__)


class UsersService:
    """Сервис для работы с пользователями"""

    @staticmethod
    async def get_users(db: Session) -> list[Users]:
        """Получить список пользователей"""
        print("db_users")
        users = db.query(Users).all()
        return users

    @staticmethod
    async def search_users(db: Session, service_id: str, query: str) -> list[Users]:
        """
        Поиск пользователей по ФИО с поддержкой частичного совпадения
        Возвращает список пользователей, где хотя бы одно слово из запроса
        совпадает с именем, фамилией или отчеством
        """
        print(service_id, query)
        if not query or not query.strip():
            return []
        
        # Разбиваем запрос на слова и очищаем от лишних пробелов
        search_terms = [term.strip() for term in query.split() if term.strip()]
        
        if not search_terms:
            return []
        
        # Начинаем с базового запроса
        query_db: Query = db.query(Users).filter(Users.service_id == service_id)
        # Создаем условия для каждого слова из запроса
        conditions = []
        for term in search_terms:
            # Для каждого слова проверяем совпадение с любым из полей ФИО
            term_condition = or_(
                Users.first_name.ilike(f'%{term}%'),
                Users.last_name.ilike(f'%{term}%'),
                Users.middle_name.ilike(f'%{term}%')
            )
            conditions.append(term_condition)
        
        # Объединяем все условия через AND (все слова должны встречаться)
        # Если нужно OR (хотя бы одно слово), замените and_ на or_
        if conditions:
            query_db = query_db.filter(and_(*conditions))
        
        # Добавляем сортировку для консистентности результатов
        query_db = query_db.order_by(Users.last_name, Users.first_name, Users.middle_name)
        
        # Выполняем запрос и возвращаем результаты
        result = query_db.all()
        return result

    @staticmethod
    async def get_user_by_id(db: Session, user_id: uuid.UUID):
        user: Users = db.query(Users).filter(Users.id == user_id).first()
        return user
    

# Глобальный экземпляр
users_service = UsersService()