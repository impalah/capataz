# Carga .env si existe (copiar antes desde .env.example) como variables de
# Make ($(SONAR_TOKEN), $(REGISTRY_USER), etc.) — a propósito SIN "export"
# global: pisaría la config de runtime que el worker espera del .env de la
# raíz del repo. Cada target que necesite algo de este .env lo pasa explícito.
-include .env

# Bundle de certificados para el target "sonar", si SonarQube usa una CA propia.
REQUESTS_CA_BUNDLE ?= /etc/ssl/certs/ca-certificates.crt

# Parte a subir con "make bump-version" — patch por defecto: make bump-version PART=minor
PART ?= patch

.PHONY: install test test-unit test-cov lint format typecheck coverage playbook-check playbook-local \
	build run sonar sonar-check bump-version clean up down logs ps

SERVICE_NAME  := capataz-runner
IMAGE_NAME    := $(SERVICE_NAME)
IMAGE_TAG     := local
DOCKER_NETWORK ?= capataz_internal
STACK_COMPOSE := docker compose --env-file ../.env -f docker-compose.yml

# --- Registry de imágenes (target "build"; sin definir en .env, falla con el motivo) ---
REGISTRY_URI      ?=
REGISTRY_USER     ?=
REGISTRY_PASSWORD ?=
REGISTRY_IMAGE    := $(REGISTRY_URI)/$(SERVICE_NAME)

# capataz-runner solo corre hoy en nodos amd64; sobreescribe desde .env si hiciera falta arm64.
PLATFORMS ?= linux/amd64

## Levanta SOLO runner + su propio Postgres/Redis dedicados (docker-compose.yml de este directorio)
up:
	$(STACK_COMPOSE) up -d --build

down:
	$(STACK_COMPOSE) down --remove-orphans

logs:
	$(STACK_COMPOSE) logs -f

ps:
	$(STACK_COMPOSE) ps

install:
	uv sync --all-groups

test test-unit:
	uv run pytest

## Igual que test, pero además genera coverage.xml (formato Cobertura, lo consume SonarQube)
test-cov:
	uv run pytest --cov --cov-report=xml

lint:
	uv run ruff check src tests

format:
	uv run ruff format --check src tests

typecheck:
	uv run mypy

coverage:
	uv run pytest --cov

playbook-check:
	uv run ansible-playbook --syntax-check -i inventories/local.yml playbooks/restart_service.yml
	uv run ansible-playbook --syntax-check -i inventories/local.yml playbooks/backup_service.yml
	uv run ansible-playbook --syntax-check -i inventories/local.yml playbooks/check_connectivity.yml

playbook-local:
	uv run ansible-playbook -i inventories/local.yml --limit local-mock playbooks/restart_service.yml --extra-vars '{"service":"example-service"}'
	uv run ansible-playbook -i inventories/local.yml --limit local-mock playbooks/backup_service.yml --extra-vars '{"service":"example-service","backup_label":"test"}'
	uv run ansible-playbook -i inventories/local.yml --limit local-mock playbooks/check_connectivity.yml

## Sube la versión en pyproject.toml (patch por defecto — make bump-version PART=minor|major)
bump-version:
	@v=$$(uvx --from=toml-cli toml get --toml-path=pyproject.toml project.version) && \
	echo "[INFO] Versión actual: $$v" && \
	uvx --from bump2version bumpversion --allow-dirty --current-version "$$v" $(PART) pyproject.toml && \
	echo "[OK] Versión subida ($(PART))"

## Construir imagen (multi-arch si PLATFORMS lo indica), etiquetarla y subirla al registry
build:
	@test -n "$(REGISTRY_URI)" || (echo "ERROR: define REGISTRY_URI en .env (copiar desde .env.example)"; exit 1)
	@test -n "$(REGISTRY_USER)" || (echo "ERROR: define REGISTRY_USER en .env (copiar desde .env.example)"; exit 1)
	@test -n "$(REGISTRY_PASSWORD)" || (echo "ERROR: define REGISTRY_PASSWORD en .env (copiar desde .env.example)"; exit 1)
	@VERSION=$$(uvx --from=toml-cli toml get --toml-path=pyproject.toml project.version) && \
	echo "[INFO] Construyendo $(SERVICE_NAME) versión $$VERSION para $(PLATFORMS)" && \
	echo "$(REGISTRY_PASSWORD)" | docker login $(REGISTRY_URI) -u "$(REGISTRY_USER)" --password-stdin && \
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) . && \
	docker buildx build \
		--platform $(PLATFORMS) \
		-t $(REGISTRY_IMAGE):$$VERSION \
		-t $(REGISTRY_IMAGE):latest \
		--push \
		. && \
	echo "[OK] Subido ($(PLATFORMS)): $(REGISTRY_IMAGE):$$VERSION y $(REGISTRY_IMAGE):latest"

## Arrancar contenedor de pruebas local (lee el .env de runtime de la raíz del repo)
run:
	docker run --rm -it \
		--network $(DOCKER_NETWORK) \
		--env-file ../.env \
		$(IMAGE_NAME):$(IMAGE_TAG)

## Analizar con SonarQube (pysonar) — requiere SONAR_HOST_URL y SONAR_TOKEN en .env
sonar:
	@test -n "$(SONAR_TOKEN)" || (echo "ERROR: define SONAR_TOKEN en .env (copiar desde .env.example)"; exit 1)
	@test -n "$(SONAR_HOST_URL)" || (echo "ERROR: define SONAR_HOST_URL en .env (copiar desde .env.example)"; exit 1)
	find . -path ./.venv -prune -o -iname "__pycache__" -print0 2>/dev/null | xargs -0 rm -rf
	SONAR_HOST_URL=$(SONAR_HOST_URL) SONAR_TOKEN=$(SONAR_TOKEN) REQUESTS_CA_BUNDLE=$(REQUESTS_CA_BUNDLE) uv run pysonar

## Cobertura + análisis SonarQube en un solo paso
sonar-check: test-cov sonar

## Limpiar imágenes Docker locales construidas por build/run
clean:
	docker rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true
	docker rmi $(REGISTRY_IMAGE):latest 2>/dev/null || true
