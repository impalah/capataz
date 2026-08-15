# Carga .env si existe (copiar antes desde .env.example) — mismo fichero que las variables de
# config en tiempo de ejecución CAPATAZ_FRONTEND_* (ver docker-run, más abajo) más las
# variables solo-Makefile (REGISTRY_*, SONAR_*). A propósito SIN "export" global: cada target
# que necesite algo de aquí lo pasa explícito en su propio comando.
-include .env

REQUESTS_CA_BUNDLE ?= /etc/ssl/certs/ca-certificates.crt

# Parte a subir con "make bump-version" — patch por defecto: make bump-version PART=minor
PART ?= patch

.PHONY: install dev build build-package test coverage lint format typecheck e2e \
	docker-build docker-run sonar sonar-check bump-version clean up down logs ps

SERVICE_NAME   := capataz-frontend
IMAGE_NAME     := $(SERVICE_NAME)
IMAGE_TAG      := local
PORT           := 8090
DOCKER_NETWORK ?= capataz_edge
STACK_COMPOSE  := docker compose --env-file ../.env -f docker-compose.yml

# --- Registry de imágenes (target "docker-build"; sin definir en .env, falla con el motivo) ---
REGISTRY_URI      ?=
REGISTRY_USER     ?=
REGISTRY_PASSWORD ?=
REGISTRY_IMAGE    := $(REGISTRY_URI)/$(SERVICE_NAME)

# capataz-frontend solo corre hoy en nodos amd64; sobreescribe desde .env si hiciera falta arm64.
PLATFORMS ?= linux/amd64

# Config en tiempo de ejecución del contenedor (ver frontend/nginx/40-render-runtime-config.sh y
# docs/adr/007-runtime-frontend-config.es.md) — ya no son build args de Vite: la imagen se construye
# una sola vez y esto se pasa a "docker run"/compose. Valores por defecto iguales a docker-compose.yml.
CAPATAZ_FRONTEND_API_BASE_URL  ?= /api/v1
CAPATAZ_FRONTEND_USE_MSW       ?= false
CAPATAZ_FRONTEND_DEV_USER      ?= ana.admin
CAPATAZ_FRONTEND_OIDC_ISSUER   ?=
CAPATAZ_FRONTEND_OIDC_CLIENT_ID ?=
CAPATAZ_FRONTEND_OIDC_SCOPE    ?= openid profile email groups

## Levanta SOLO frontend (docker-compose.yml de este directorio; ver comentarios del fichero
## sobre cómo resuelve el hostname "api" del proxy de nginx sin api/runner/postgres/redis)
up:
	$(STACK_COMPOSE) up -d --build

down:
	$(STACK_COMPOSE) down --remove-orphans

logs:
	$(STACK_COMPOSE) logs -f

ps:
	$(STACK_COMPOSE) ps

install:
	npm ci

dev:
	npm run dev

build:
	npm run build

## Build + empaqueta dist/ en un zip listo para copiar al webroot de un nginx propio o subir a
## S3/CloudFront. El config.js incluido trae los defaults de desarrollo (frontend/public/config.js)
## — sustitúyelo por el de tu entorno antes de servirlo; ver docs/07-operations.es.md y
## docs/adr/007-runtime-frontend-config.es.md.
build-package: build
	@VERSION=$$(node -p "require('./package.json').version") && \
	rm -f $(SERVICE_NAME)-$$VERSION.zip && \
	(cd dist && zip -qr ../$(SERVICE_NAME)-$$VERSION.zip .) && \
	echo "[OK] Generado $(SERVICE_NAME)-$$VERSION.zip (contenido de dist/)"

test:
	npm run test:unit

coverage:
	npm run test:unit

lint:
	npm run lint

format:
	npm run format

typecheck:
	npm run typecheck

e2e:
	npm run e2e

## Sube la versión en package.json (patch por defecto — make bump-version PART=minor|major)
bump-version:
	@npm version $(PART) --no-git-tag-version && \
	echo "[OK] Versión subida ($(PART))"

## Construir imagen (multi-arch si PLATFORMS lo indica), etiquetarla y subirla al registry
docker-build:
	@test -n "$(REGISTRY_URI)" || (echo "ERROR: define REGISTRY_URI en .env (copiar desde .env.example)"; exit 1)
	@test -n "$(REGISTRY_USER)" || (echo "ERROR: define REGISTRY_USER en .env (copiar desde .env.example)"; exit 1)
	@test -n "$(REGISTRY_PASSWORD)" || (echo "ERROR: define REGISTRY_PASSWORD en .env (copiar desde .env.example)"; exit 1)
	@VERSION=$$(node -p "require('./package.json').version") && \
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

## Arrancar el contenedor con nginx propio (sirve dist/ + proxy /api/ a la API) — alternativa
## a servir el zip de build-package desde un nginx externo, ver docker-compose.yml
docker-run:
	docker run --rm -it \
		-p $(PORT):80 \
		--network $(DOCKER_NETWORK) \
		-e CAPATAZ_FRONTEND_API_BASE_URL="$(CAPATAZ_FRONTEND_API_BASE_URL)" \
		-e CAPATAZ_FRONTEND_USE_MSW="$(CAPATAZ_FRONTEND_USE_MSW)" \
		-e CAPATAZ_FRONTEND_DEV_USER="$(CAPATAZ_FRONTEND_DEV_USER)" \
		-e CAPATAZ_FRONTEND_OIDC_ISSUER="$(CAPATAZ_FRONTEND_OIDC_ISSUER)" \
		-e CAPATAZ_FRONTEND_OIDC_CLIENT_ID="$(CAPATAZ_FRONTEND_OIDC_CLIENT_ID)" \
		-e CAPATAZ_FRONTEND_OIDC_SCOPE="$(CAPATAZ_FRONTEND_OIDC_SCOPE)" \
		$(IMAGE_NAME):$(IMAGE_TAG)

## Analizar con SonarQube (sonar-scanner vía npx) — requiere SONAR_HOST_URL y SONAR_TOKEN en .env
sonar:
	@test -n "$(SONAR_TOKEN)" || (echo "ERROR: define SONAR_TOKEN en .env (copiar desde .env.example)"; exit 1)
	@test -n "$(SONAR_HOST_URL)" || (echo "ERROR: define SONAR_HOST_URL en .env (copiar desde .env.example)"; exit 1)
	SONAR_HOST_URL=$(SONAR_HOST_URL) SONAR_TOKEN=$(SONAR_TOKEN) NODE_EXTRA_CA_CERTS=$(REQUESTS_CA_BUNDLE) npx --yes @sonar/scan

## Cobertura + análisis SonarQube en un solo paso
sonar-check: coverage sonar

## Limpiar artefactos locales (dist, coverage, zip) e imágenes Docker construidas por docker-build/docker-run
clean:
	rm -rf dist coverage $(SERVICE_NAME)-*.zip
	docker rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true
	docker rmi $(REGISTRY_IMAGE):latest 2>/dev/null || true

