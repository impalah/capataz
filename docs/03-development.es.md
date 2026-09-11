# Desarrollo

*Idioma: **Español** · [English](03-development.en.md)*

## Puesta en marcha

```bash
cp .env.example .env
make bootstrap
# crea secrets/* siguiendo README.md
make build
make up
make migrate
make seed-catalog
```

No hay override Docker de hot reload para el stack completo. Para hot reload, ejecuta cada proyecto en nativo — cada uno tiene su propio Makefile y, para Python, `uv`:

```bash
make -C api install
make -C runner install
make -C frontend install
make -C api dev
make -C frontend dev
```

No uses `pip`, `requirements.txt` ni Poetry. Los lockfiles `api/uv.lock` y `runner/uv.lock` se versionan y se consumen con `uv sync --frozen` en CI.

## Flujo de calidad

```bash
make lint
make format
make typecheck
make test-unit
make test-integration
make coverage
make test-e2e
```

El objetivo `format` modifica archivos; en revisión usa el formatter en modo comprobación que provea cada subproyecto. Los cambios deben conservar cobertura global >=80% en backend y frontend, tipos estrictos y tests de las políticas críticas. `pre-commit` es opcional pero recomendable para format/lint antes de abrir un PR.

## Tests end-to-end (Playwright)

La suite e2e (`frontend/tests/e2e/`) maneja un Chromium real contra el stack real: la API en modo `dev_mock` con `catalog/services.example.yaml` importado al arrancar, y el runner consumiendo la cola. No se simula nada.

**1. Requisitos (una vez):** Docker con Compose v2, Node 22, `curl` y el navegador:

```bash
make -C frontend install
cd frontend && npx playwright install --with-deps chromium && cd ..
```

**2. Configuración:** `.env` copiado de `.env.example`, cuyos valores por defecto son justo los que necesita la suite — `CAPATAZ_ENV=development`, `CAPATAZ_AUTH_MODE=dev_mock`, `CAPATAZ_CORS_ORIGINS` incluyendo `http://localhost:9000` (el servidor de desarrollo Vite que arranca Playwright) y `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml`. Si defines `SSL_CERT_FILE`, el bundle tiene que existir en `certs/` (`make trust-ca`).

**3. Secretos** (`secrets/`, ignorado por git): `postgres_password`, `redis_password`, `database_url` y `redis_url` como en el quick start del README; `cognito_client_secret` (cualquier marcador en `dev_mock`); y la clave maestra de recursos:

```bash
make bootstrap   # crea secrets/ y resources/
python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' > secrets/resources_master_key
chmod 644 secrets/*   # los contenedores corren como uid 10001, no como tu usuario
```

**4. Recursos** (`resources/`, ignorado por git, montado en solo lectura en la api como `CAPATAZ_RESOURCES_DIR`): el catálogo de ejemplo declara cuatro recursos con orígenes `{file: ...}`, y la importación del arranque — y con ella `/health/ready` — falla si falta alguno. Para la suite bastan marcadores:

```bash
printf 'e2e-placeholder-token\n' > resources/portainer_token
printf 'e2e-placeholder-key\n' > resources/runner_ssh_private_key
printf 'placeholder.example ssh-ed25519 AAAA\n' > resources/runner_known_hosts
printf 'e2e-placeholder-vault\n' > resources/ansible_vault_password
chmod 644 resources/*
```

Con marcadores, el estado de los servicios sale como desconocido (Portainer rechaza el token); los tests no dependen de él. Si aún tienes los secretos reales anteriores al ADR-008, copiarlos en su lugar (`cp secrets/{portainer_token,runner_ssh_private_key,runner_known_hosts,ansible_vault_password} resources/`) da estados reales.

**5. Ejecución:**

```bash
make test-e2e
```

Construye las imágenes, hace `docker compose up -d`, espera a `http://localhost:8000/health/ready` (la api aplica las migraciones e importa el catálogo mientras arranca) y luego ejecuta `make -C frontend e2e`: Playwright arranca `npm run dev` en el puerto 9000, cuyo `public/config.js` versionado ya apunta a `http://localhost:8000/api/v1` en modo `dev_mock`, con el navegador en locale `es-ES` (los specs comprueban textos en castellano). Para repetir solo la parte del navegador contra el stack ya levantado: `make -C frontend e2e`, o `cd frontend && npx playwright test -g "viewer"`.

**Qué cubre:** la navegación y la confirmación de una acción `critical` (crea una ejecución `backup` real, que el runner procesa a través del conector `ansible` y sus recursos descifrados), una importación dry-run de catálogo v2, las pestañas Conectores/Recursos (solo metadatos — nunca el contenido de un recurso) y la vista de solo lectura del viewer.

**Si falla:**

- `curl http://localhost:8000/health/ready` y `docker compose logs api`: busca las migraciones (`Running upgrade ... -> 20260912_0009`) y los errores de importación del catálogo, que llevan su línea del YAML (p. ej. un fichero que falta en `resources/`).
- Cada test fallido deja la instantánea de la página en `frontend/test-results/*/error-context.md`; `cd frontend && npx playwright show-report` abre el informe completo.
- Un volumen de base de datos de una versión anterior se migra in situ (la migración `0009` no tiene vuelta atrás). Para empezar de cero: `make clean` (borra los volúmenes tras pedir confirmación).
- Puertos 8000 o 9000 ocupados: para lo que los esté usando (p. ej. un `make -C frontend dev`, que fuera de CI Playwright reutilizaría).

**Limpieza:** `make down` conserva los datos; `make clean` los borra.

## Migraciones y datos de prueba

```bash
make migrate
make migration name="add_service_metadata"
make seed-catalog
make export-catalog > catalog/export.yaml
```

Las migraciones se crean desde `api`, se revisan manualmente y nunca se editan una vez aplicadas en un entorno compartido. Los fixtures no contienen tokens, hosts privados reales ni secretos. El catálogo de ejemplo contiene solo definiciones declarativas.

## Convenciones de contribución

- `Service.id` es un slug inmutable; tablas en plural snake_case y otros IDs UUID.
- No acoples `application` a FastAPI, SQLAlchemy, Celery ni `httpx`; añade un puerto y un adapter.
- Toda mutación exige identidad, source, correlation ID y auditoría.
- La cola recibe solo `execution_id`. Relee la definición desde PostgreSQL al ejecutar.
- Nunca añadas un campo `command`, una URL de ejecución de cliente, secretos en YAML o interpolación shell.
- Añade tests para estado agregado, RBAC, validación YAML, transiciones, sanitización y adapters modificados.

## Entornos y auth de desarrollo

`CAPATAZ_AUTH_MODE=dev_mock` es una facilidad estrictamente local y solo se permite junto con `CAPATAZ_ENV=development`. Prueba roles con:

```bash
curl -H 'X-Dev-User: ana' \
  -H 'X-Dev-Groups: capataz-admin' \
  http://localhost:8000/api/v1/services
```

No introduzcas una condición que active este modo por ausencia de configuración; producción debe requerir Cognito correctamente configurado.
