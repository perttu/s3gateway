.PHONY: help build up down logs clean restart shell-backend shell-frontend

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build Docker images
	docker-compose build

up: ## Start all services
	docker-compose up -d

down: ## Stop all services
	docker-compose down

logs: ## View logs from all services
	docker-compose logs -f

logs-backend: ## View backend logs
	docker-compose logs -f backend

logs-frontend: ## View frontend logs
	docker-compose logs -f frontend

restart: ## Restart all services
	docker-compose restart

clean: ## Remove containers and volumes
	docker-compose down -v

shell-backend: ## Open shell in backend container
	docker-compose exec backend /bin/bash

shell-frontend: ## Open shell in frontend container
	docker-compose exec frontend /bin/sh

dev: ## Start in development mode with hot reload
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

dev-build: ## Build for development
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml build

ps: ## Show running containers
	docker-compose ps 