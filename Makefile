SHELL := /bin/sh
.DEFAULT_GOAL := help
COMPOSE ?= docker compose
COMPOSE_FILES ?= -f docker-compose.yml
SERVICE ?=
name ?=
API_URL ?= http://localhost:8000/api/v1
API_AUTHORIZATION ?=
CA_URL ?= http://pi-dns.home.arpa/ca.crt

.PHONY: help bootstrap up down logs ps build test test-unit test-integration test-e2e lint format typecheck coverage migrate migration seed-catalog export-catalog clean security-scan trust-ca

help: ## Lista los objetivos disponibles
	@awk 'BEGIN {FS = ":.*##"}; /^[a-zA-Z0-9_-]+:.*##/ {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Copia .env.example y prepara directorios locales (no crea secretos)
	@test -f .env || cp .env.example .env
	@mkdir -p secrets catalog
	@touch secrets/.gitkeep
	@echo "Configuración creada. Genera los secretos siguiendo README.md antes de usar Compose."

trust-ca: ## Descarga tu CA interna (CA_URL) y genera certs/ca-bundle.pem para api/runner
	@mkdir -p certs
	curl -fsSL $(CA_URL) -o certs/homelab-ca.crt
	cat /etc/ssl/certs/ca-certificates.crt certs/homelab-ca.crt > certs/ca-bundle.pem
	@echo "certs/ca-bundle.pem generado. Añade SSL_CERT_FILE=/run/ca-certs/ca-bundle.pem a tu .env y reinicia api/runner."

up: ## Levanta el stack en segundo plano
	$(COMPOSE) $(COMPOSE_FILES) up -d --build

down: ## Detiene el stack sin borrar datos persistentes
	$(COMPOSE) $(COMPOSE_FILES) down --remove-orphans

logs: ## Sigue logs; usar service=api para filtrar
	$(COMPOSE) $(COMPOSE_FILES) logs -f $(SERVICE)

ps: ## Muestra el estado de los contenedores
	$(COMPOSE) $(COMPOSE_FILES) ps

build: ## Construye las tres imágenes de aplicación
	$(COMPOSE) $(COMPOSE_FILES) build frontend api runner

test: test-unit test-integration ## Ejecuta tests unitarios e integración de todos los proyectos

test-unit: ## Ejecuta tests unitarios backend, runner y frontend
	$(MAKE) -C api test-unit
	$(MAKE) -C api test-architecture
	$(MAKE) -C runner test
	$(MAKE) -C frontend test

test-integration: ## Ejecuta integración del backend
	$(MAKE) -C api test-integration

test-e2e: ## Ejecuta Playwright contra el stack de pruebas
	$(COMPOSE) $(COMPOSE_FILES) up -d --build
	$(MAKE) -C frontend e2e

lint: ## Ejecuta linters de los tres proyectos
	$(MAKE) -C api lint
	$(MAKE) -C runner lint
	$(MAKE) -C frontend lint

format: ## Aplica formatters de los tres proyectos
	$(MAKE) -C api format
	$(MAKE) -C runner format
	$(MAKE) -C frontend format

typecheck: ## Ejecuta comprobación estática de tipos
	$(MAKE) -C api typecheck
	$(MAKE) -C runner typecheck
	$(MAKE) -C frontend typecheck

coverage: ## Genera/verifica la cobertura de backend y frontend
	$(MAKE) -C api test
	$(MAKE) -C frontend coverage

migrate: ## Aplica las migraciones Alembic en la API del stack
	$(COMPOSE) $(COMPOSE_FILES) exec api alembic upgrade head

migration: ## Crea una migración Alembic; requiere name="descripcion"
	@test -n "$(name)" || (echo 'Uso: make migration name="descripcion"' >&2; exit 2)
	$(MAKE) -C api migration name="$(name)"

seed-catalog: ## Importa idempotentemente catalog/services.example.yaml
	CAPATAZ_API_URL="$(API_URL)" CAPATAZ_API_AUTHORIZATION="$(API_AUTHORIZATION)" python3 infra/docker/catalog_client.py import catalog/services.example.yaml

export-catalog: ## Exporta el catálogo limpio a stdout
	CAPATAZ_API_URL="$(API_URL)" CAPATAZ_API_AUTHORIZATION="$(API_AUTHORIZATION)" python3 infra/docker/catalog_client.py export

clean: ## Elimina contenedores, redes, volúmenes y artefactos locales (con confirmación)
	@printf 'Esto elimina volúmenes de PostgreSQL/Redis. Escribe yes para continuar: '; read answer; test "$$answer" = yes
	$(COMPOSE) $(COMPOSE_FILES) down --volumes --remove-orphans
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache -o -name dist -o -name coverage \) -prune -exec rm -rf {} +

security-scan: ## Ejecuta gitleaks/trivy mediante contenedores sin credenciales
	docker run --rm -v "$(CURDIR):/repo:ro" zricethezav/gitleaks:v8.21.2 dir /repo --no-git
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.57.1 image --severity HIGH,CRITICAL --ignore-unfixed capataz-api:local
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.57.1 image --severity HIGH,CRITICAL --ignore-unfixed capataz-runner:local
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.57.1 image --severity HIGH,CRITICAL --ignore-unfixed capataz-frontend:local
