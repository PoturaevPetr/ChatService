#!/usr/bin/env python3
"""
Создаёт таблицу message_recipient_keys, если её нет.
Запуск: из корня проекта
  python -m scripts.create_message_recipient_keys
  или
  python scripts/create_message_recipient_keys.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.database import engine
from server.database.MessageRecipientKeys import MessageRecipientKeys


def main():
    MessageRecipientKeys.__table__.create(engine, checkfirst=True)
    print("OK: table message_recipient_keys exists or was created.")


if __name__ == "__main__":
    main()
