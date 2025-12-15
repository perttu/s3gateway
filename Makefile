.PHONY: help build up down logs clean restart shell-backend shell-frontend

COMPOSE_CMD = docker-compose -f docker/docker-compose.yml
DEV_COMPOSE_CMD = docker-compose -f docker/docker-compose.yml -f docker/dev/docker-compose.dev.yml
help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build Docker images
	$(COMPOSE_CMD) build

up: ## Start all services
	$(COMPOSE_CMD) up -d

down: ## Stop all services
	$(COMPOSE_CMD) down

logs: ## View logs from all services
	$(COMPOSE_CMD) logs -f

logs-backend: ## View backend logs
	$(COMPOSE_CMD) logs -f backend

logs-frontend: ## View frontend logs
	$(COMPOSE_CMD) logs -f frontend

restart: ## Restart all services
	$(COMPOSE_CMD) restart

clean: ## Remove containers and volumes
	$(COMPOSE_CMD) down -v

shell-backend: ## Open shell in backend container
	$(COMPOSE_CMD) exec backend /bin/bash

shell-frontend: ## Open shell in frontend container
	$(COMPOSE_CMD) exec frontend /bin/sh

dev: ## Start in development mode with hot reload
	$(DEV_COMPOSE_CMD) up

dev-build: ## Build for development
	$(DEV_COMPOSE_CMD) build

ps: ## Show running containers
	$(COMPOSE_CMD) ps
