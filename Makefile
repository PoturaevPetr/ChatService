.PHONY: help up down restart logs build install clean

help: ## Показать эту помощь
	@echo "Доступные команды:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Запустить все сервисы (docker-compose)
	docker-compose up -d

down: ## Остановить все сервисы
	docker-compose down

restart: ## Перезапустить все сервисы
	docker-compose restart

logs: ## Показать логи API
	docker-compose logs -f api

ps: ## Показать статус контейнеров
	docker-compose ps

build: ## Пересобрать образы
	docker-compose build --no-cache

install: ## Установить зависимости локально
	pip install -r requirements.txt

run: ## Запустить локально (без docker)
	python start.py

clean: ## Очистить все контейнеры и volumes
	docker-compose down -v

db-shell: ## Открыть PostgreSQL shell
	docker-compose exec postgres psql -U postgres -d ChatDatabase

api-shell: ## Открыть shell в API контейнере
	docker-compose exec api /bin/bash

test: ## Запустить тесты
	docker-compose exec api pytest

migrate: ## Создать миграции БД
	docker-compose exec api alembic revision --autogenerate -m "Migration"

upgrade: ## Применить миграции
	docker-compose exec api alembic upgrade head

migrate-messages-status: ## Добавить колонку status в messages (если 500 на GET /api/v1/messages/)
	@echo "Applying messages.status migration..."
	docker-compose exec -T postgres psql -U postgres -d ChatDatabase < migrations/add_messages_status.sql
	@echo "Done. Restart API if needed: docker-compose restart api"

migrate-messages-variant-a: ## Вариант A: nullable recipient_id + таблица message_reads (перед деплоем нового API)
	@echo "Applying migrate_messages_variant_a_message_reads.sql..."
	docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1 < migrations/migrate_messages_variant_a_message_reads.sql
	@echo "Done. Deploy new API/worker after this."

migrate-rooms-avatar: ## Колонка rooms.avatar (аватар группы)
	docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1 < migrations/add_rooms_avatar.sql
	@echo "Done."

migrate-performance-indexes: ## Индексы room_user + messages (ленты и membership)
	@echo "Applying migrations/add_performance_indexes.sql..."
	docker-compose exec -T postgres psql -U postgres -d ChatDatabase -v ON_ERROR_STOP=1 < migrations/add_performance_indexes.sql
	@echo "Done."
