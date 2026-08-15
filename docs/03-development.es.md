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
