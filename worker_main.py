"""
Точка входа для воркера доставки сообщений.
Запуск: python worker_main.py
"""
from server.worker.app import app
from server.settings import settings
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "server.worker.app:app",
        host="0.0.0.0",
        port=settings.WORKER_PORT,
        reload=settings.DEBUG,
    )
