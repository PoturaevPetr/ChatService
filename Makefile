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
