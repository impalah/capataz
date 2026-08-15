# Operaciones

*Idioma: **Español** · [English](07-operations.en.md)*

## Despliegue Compose

1. Copia `.env.example` a `.env`, completa únicamente valores no sensibles y crea los siete ficheros de `secrets/` siguiendo el README.
2. Protege los secretos: `chmod 600 secrets/*`; restringe también el directorio (`chmod 700 secrets`).
3. Comprueba la composición antes de arrancar: `docker compose config`.
4. Construye y arranca: `make build && make up`.
5. Espera a `make ps`, aplica `make migrate` y carga el catálogo con `make seed-catalog` si no se ha importado al inicio.

El perfil normal publica solo frontend `8080` y API `8000`. PostgreSQL y Redis permanecen en la red `internal` y nunca se publican.

## Despliegue standalone del frontend (S3+CloudFront / Nginx propio)

`frontend/dist/` es un artefacto estático (HTML/JS/CSS con hash + `config.js`) que no necesita
Docker ni Nginx para existir — solo un servidor de ficheros estáticos. La configuración
(`API_BASE_URL`, `USE_MSW`, `OIDC_*`) se lee en tiempo de ejecución del navegador desde
`config.js`, no se hornea en el build (ver
[ADR 007](adr/007-runtime-frontend-config.es.md)), así que **un único build sirve para cualquier
número de entornos**: solo cambia `config.js` entre ellos.

### 1. Construir una vez

```bash
cd frontend
npm ci
make build-package   # genera dist/ + capataz-frontend-<version>.zip
```

El `config.js` incluido en ese `dist/`/zip es el committeado en `frontend/public/config.js`
(defaults de desarrollo local: `USE_MSW: true`, API en `http://localhost:8000/api/v1`). **No sirve
tal cual en un despliegue real** — siempre hay que sustituirlo, ver el paso 2.

### 2. Configurar `config.js` por entorno

Antes de subir/servir `dist/`, sobrescribe `dist/config.js` (o el `config.js` ya desplegado, sin
tocar el resto del artefacto) con los valores reales del entorno:

```js
window.__APP_CONFIG__ = {
  API_BASE_URL: 'https://api.tudominio.com/api/v1', // o '/api/v1' si vas a proxear, ver 3b/4
  USE_MSW: false, // false siempre en cualquier despliegue alcanzable desde fuera de tu LAN
  OIDC_ISSUER: 'https://tu-issuer/...',
  OIDC_CLIENT_ID: 'xxxxx',
  OIDC_SCOPE: 'openid profile email groups',
}
```

**`USE_MSW: true` activa el modo `dev_mock` (sin login) — ver la nota de seguridad al final de
esta sección antes de desplegar nada alcanzable desde fuera de tu red de confianza.**

### 3. S3 + CloudFront

a. Sube el contenido de `dist/` (ya con su `config.js` real) a un bucket S3, sirviéndolo vía
   CloudFront con `index.html` como *default root object* y como *error document* de los 403/404
   (necesario para que las rutas de Vue Router, p. ej. `/services/x`, funcionen al recargar la
   página — equivalente al `try_files … /index.html` de `default.conf`).
b. Cache diferenciada por tipo de fichero — esto es lo único realmente específico de un CDN:
   - `config.js`: `Cache-Control: no-store` (o TTL de segundos como mucho). Un `invalidation` de
     CloudFront tras redesplegarlo no basta por sí solo si el navegador ya lo cacheó localmente.
   - `assets/*` (JS/CSS con hash en el nombre): cache larga e inmutable
     (`public, max-age=31536000, immutable`) — un redeploy genera nombres de fichero distintos, así
     que no hay riesgo de servir una versión vieja.
   - `index.html`: cache corta o `no-cache` (revalida siempre), igual que `config.js`.
c. La API necesita ser alcanzable desde el navegador del usuario. Dos opciones:
   - **URL absoluta + CORS** (más simple): `API_BASE_URL: 'https://api.tudominio.com/api/v1'` en
     `config.js`, y añade el dominio de CloudFront a `CAPATAZ_CORS_ORIGINS` en el `.env` de la API.
     No hace falta `Access-Control-Allow-Credentials`: la autenticación va por
     `Authorization: Bearer` (OIDC), nunca por cookies.
   - **Segundo origin/behavior en CloudFront** para `/api/*` apuntando al origin de la API,
     replicando lo que hace `location /api/` en `default.conf`: entonces `config.js` puede seguir
     usando `API_BASE_URL: '/api/v1'` (relativo), sin tocar CORS.

### 4. Nginx propio (sin Docker)

```bash
cp -r dist/* /ruta/al/webroot/nginx/
```

Replica el `server{}` de `frontend/nginx/default.conf`: `try_files $uri $uri/ /index.html;` para
las rutas de Vue Router, y si quieres mantener `API_BASE_URL: '/api/v1'` (relativo) en vez de una
URL absoluta + CORS, el mismo bloque `location /api/ { proxy_pass … }` mismo apuntando al host
real de tu API en vez de al nombre interno `api` de la red de Compose. Añade también
`add_header Cache-Control "no-store" always;` en un `location = /config.js` dedicado, por la misma
razón que en CloudFront (punto 3b).

### Recordatorios de seguridad para cualquier despliegue standalone

- **`USE_MSW` debe ir a `false`** en cualquier entorno alcanzable desde fuera de tu red de
  confianza — es el modo sin autenticación real (`CLAUDE.md`). El frontend por sí solo no es
  barrera suficiente: confirma también que la API de ese entorno tiene
  `CAPATAZ_AUTH_MODE` distinto de `dev_mock`.
- **`OIDC_ISSUER`/`OIDC_CLIENT_ID` deben apuntar a un IdP real** (ver
  [Authentik](09-authentik-oidc-setup.es.md) / [Cognito](10-cognito-oidc-setup.es.md)) en cualquier
  entorno que no sea puramente de desarrollo local.

## Copia y restauración de PostgreSQL

Haz el backup desde una máquina con acceso al daemon Docker y guárdalo cifrado fuera del host:

```bash
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
docker compose exec -T postgres pg_dump -U capataz -Fc capataz > "backups/capataz-${stamp}.dump"
sha256sum "backups/capataz-${stamp}.dump" > "backups/capataz-${stamp}.dump.sha256"
```

Para restaurar, detén API y runner para evitar escrituras, verifica el checksum y restaura en una ventana de mantenimiento:

```bash
docker compose stop api runner
docker compose exec -T postgres dropdb -U capataz capataz
docker compose exec -T postgres createdb -U capataz capataz
cat backups/capataz-YYYYMMDDTHHMMSSZ.dump | docker compose exec -T postgres pg_restore -U capataz -d capataz --clean --if-exists
docker compose start api runner
make migrate
```

Prueba restauraciones periódicamente en un entorno aislado. Redis no es fuente de verdad: puede vaciarse y se regeneran cachés/cola según la política de ejecución, pero antes de hacerlo revisa ejecuciones en curso.

## Token de Portainer

Capataz llama a la API de Portainer (`X-API-Key`) para el estado por contenedor y, desde el runner, para las acciones allow-listed de tipo `portainer`. El token vive en `secrets/portainer_token` (ver README) y se lee en `infrastructure/secrets/file_secret_reader.py`.

1. En Portainer, crea un usuario dedicado para Capataz (no reutilices tu cuenta de administrador personal) y limita su acceso, vía **Teams**/**Environment access**, únicamente a los entornos (endpoints) que Capataz debe consultar u operar.
2. Inicia sesión con ese usuario y ve a **Mi cuenta** (icono de usuario, arriba a la derecha) → **Access tokens** ("Tokens de acceso").
3. **Add access token**: ponle una descripción reconocible (p. ej. `capataz-api`) para poder revocarlo sin ambigüedad más adelante.
4. Portainer muestra el token en texto plano **una sola vez**. Cópialo de inmediato:

   ```bash
   echo 'TOKEN_GENERADO' > secrets/portainer_token
   chmod 600 secrets/portainer_token
   docker compose up -d --no-deps --force-recreate api runner
   ```

5. Verifica: `docker compose logs -f api` no debe mostrar `Portainer authentication was rejected`, y una tarjeta de servicio con contenedores de ese entorno debe pasar de "Desconocido" a un estado real tras pulsar "Actualizar estado".

Este token requiere disponer de un usuario Portainer separado con permisos ya limitados a los entornos relevantes — Portainer CE no ofrece tokens de acceso con alcance propio más restringido que el del usuario que los genera. Trátalo como cualquier otra credencial de la sección de rotación siguiente.

## Rotación de credenciales

1. Crea el valor nuevo en el proveedor correspondiente y anota una ventana de cambio.
2. Sustituye el fichero de `secrets/` con `umask 077`, conserva temporalmente un rollback seguro y aplica `chmod 600`.
3. Reinicia únicamente consumidores: `docker compose up -d --force-recreate api runner` (y `postgres`/`redis` cuando rote su contraseña).
4. Verifica `/health/ready`, logs y una operación de lectura; revoca el valor anterior en el proveedor.

Para contraseñas de PostgreSQL/Redis, la rotación requiere cambiar también la credencial interna de la base/broker de forma coordinada. Para Portainer limita el token al entorno y operaciones necesarias; el runner solo recibe `portainer_token` porque ejecuta acciones de plataforma. Cognito solo llega a `api`. Nunca rotar una clave SSH personal: usa una cuenta de automatización dedicada y `known_hosts` fijado.

## Gestión del catálogo

- Antes de importar: `POST /api/v1/catalog/import` con `{"yaml":"...","dry_run":true}` o la interfaz administrativa para obtener errores por línea/campo.
- Importación real: `make seed-catalog` usa el endpoint autenticado (por defecto el modo local `dev_mock`). Con Cognito exporta `API_AUTHORIZATION='Bearer <token>'` al invocar Make; la API hace upsert transaccional por el `id` lógico del servicio y el ID no se reutiliza para otro servicio.
- Exportación: `make export-catalog > catalog/export.yaml`; revísalo y elimina metadatos que no deban versionarse.
- Arranque: `CAPATAZ_INITIAL_CATALOG_YAML_PATH=/app/catalog/services.example.yaml` monta e importa el catálogo de ejemplo. Si existe la ruta pero es inválida o falta, readiness debe fallar con un mensaje claro; no se ignora.

## Monitorización y logs

`docker compose logs -f api`, `docker compose logs -f runner` y la búsqueda por `X-Request-ID` son el primer punto de observación. En producción activa `CAPATAZ_LOG_JSON=true` y lleva stdout a tu colector. Las tarjetas se alimentan de cache con TTL `CAPATAZ_STATUS_CACHE_TTL_SECONDS`; se puede lanzar refresh explícito.

Grafana y Loki se usan con deep-links declarados. Mide como mínimo salud de procesos, disponibilidad PostgreSQL/Redis, latencia/error del API, profundidad de `automation`, ejecuciones terminales por estado, duración y fallos de integraciones. No incluyas tokens, YAML sin sanitizar ni secretos como labels o atributos de logs.

## Actualización y rollback

1. Lee notas de versión y valida backups/restauración.
2. En una copia del entorno ejecuta `docker compose build`, tests y `docker compose config`.
3. Haz backup PostgreSQL, exporta catálogo y anota las versiones de imágenes actuales (`docker compose images`).
4. En producción: `make build && make up && make migrate`; observa healthchecks y una acción `read` inocua.
5. Si falla, vuelve a las etiquetas/commit de imagen anteriores y ejecuta `docker compose up -d`. Las migraciones deben ser expand/contract; si una migración no es reversible, restaura la copia de seguridad según el plan de release.

No uses `make clean` como operación normal: borra volúmenes tras confirmación y se reserva para desarrollo desechable.
