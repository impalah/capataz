# ADR 007: Configuración del frontend en tiempo de ejecución (`config.js`), no en build

*Idioma: **Español** · [English](007-runtime-frontend-config.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-15

## Contexto

Hasta ahora el frontend leía `VITE_API_BASE_URL`/`VITE_USE_MSW`/`VITE_OIDC_ISSUER`/
`VITE_OIDC_CLIENT_ID`/`VITE_OIDC_SCOPE` vía `import.meta.env.VITE_*`. Vite sustituye
`import.meta.env.VITE_*` por su valor literal en el momento de `vite build`, así que esos valores
quedaban horneados dentro del JavaScript estático de `dist/`. En `frontend/Dockerfile` esto se
traducía en cinco `ARG` pasados como `--build-arg` desde `docker-compose.yml` (a su vez
interpolados desde `.env`); cambiar cualquiera de ellos exigía reconstruir la imagen
(`make build`/`docker compose build frontend`), no solo reiniciar el contenedor.

Ese acoplamiento era manejable mientras el único destino de despliegue fuera "la imagen Docker de
este repo, en este homelab". Pero Capataz debe poder distribuirse como un paquete que cualquiera
despliegue en su propio entorno — Docker propio, S3+CloudFront, un Nginx sin relación con este
repo — y cada entorno tiene su propia URL de API y su propio proveedor OIDC. Con el diseño
anterior eso significaba una imagen Docker (o un `dist/` de `vite build`) distinto por entorno,
construido con sus propios `--build-arg`. Un `dist/` estático servido desde S3/CloudFront ni
siquiera pasa por un build controlado por este repo en el momento del despliegue — no hay dónde
inyectar un `--build-arg`.

## Decisión

La configuración del frontend deja de leerse de `import.meta.env` y pasa a leerse en tiempo de
ejecución del navegador desde `window.__APP_CONFIG__`, poblado por un script plano `/config.js`
cargado en `index.html` **antes** del bundle de la app:

```html
<script src="/config.js"></script>
<script type="module" src="/src/main.ts"></script>
```

`frontend/src/api/runtimeConfig.ts` centraliza la lectura (`readRuntimeConfig()`/`runtimeConfig`),
con defaults sensatos si `window.__APP_CONFIG__` falta o viene parcial; `client.ts`, `oidc.ts` y el
store `auth.ts` lo consumen en vez de `import.meta.env.VITE_*`. `frontend/src/env.d.ts` ya no
declara esas claves — no queda ningún camino de código que las lea.

`frontend/public/config.js` es un fichero **committeado**, copiado tal cual a `dist/` por Vite
(igual que cualquier otro asset de `public/`), con los defaults de desarrollo local (`USE_MSW:
true`, `API_BASE_URL: http://localhost:8000/api/v1` — el mismo target que ya asumía el
`webServer` de Playwright). Es el único fichero que cambia por entorno; el resto de `dist/`
(JS/CSS con hash, `index.html`) es idéntico sea cual sea el destino.

Dos consumidores de ese mismo `dist/`, cada uno resolviendo `config.js` a su manera:

1. **Imagen Docker** (`frontend/Dockerfile`, `docker-compose.yml`): ya no declara `ARG VITE_*`. En
   su lugar, `frontend/nginx/40-render-runtime-config.sh` — un script en
   `/docker-entrypoint.d/`, la convención estándar de la imagen base `nginxinc/nginx-unprivileged`
   para ejecutar algo antes de arrancar `nginx` — renderiza
   `frontend/nginx/config.js.template` con `envsubst` a partir de variables `CAPATAZ_FRONTEND_*`
   (pasadas por `docker-compose.yml` vía `environment:`, ya no `build.args`), y escribe el
   resultado en `/config-runtime/config.js`. `default.conf` sirve `/config.js` con un
   `location = /config.js { alias /config-runtime/config.js; }` separado del resto del árbol
   estático — que sigue en el filesystem de solo lectura (`read_only: true`) — con
   `/config-runtime` como el único tmpfs adicional, de 1 MB, dedicado a esto. Cambiar la config ya
   solo requiere recrear el contenedor (`docker compose up -d --force-recreate frontend`), no
   reconstruir la imagen.
2. **Despliegue estático** (S3+CloudFront, Nginx propio): no hay contenedor ni entrypoint. El
   operador sustituye `config.js` a mano en el `dist/` (o en el zip de `make build-package`) antes
   de subirlo, una vez por entorno. Ver la sección "Despliegue standalone" de
   `docs/07-operations.md`.

## Consecuencias

- **Un solo build sirve para todos los entornos.** `npm run build`/`make build`/`make
  docker-build` ya no toman ningún parámetro de entorno; el artefacto (`dist/` o la imagen) es
  idéntico para dev/staging/producción. Esto es justo lo que se pedía: "desplegable como paquete
  en cualquier entorno".
- **La imagen Docker también se vuelve reconfigurable sin rebuild.** No era el objetivo original,
  pero es una consecuencia directa: antes, cambiar `VITE_OIDC_ISSUER` en homelab exigía
  reconstruir; ahora basta recrear el contenedor con el nuevo valor de
  `CAPATAZ_FRONTEND_OIDC_ISSUER` en `.env`.
- **Nuevo requisito de imagen base:** `frontend/Dockerfile` instala `gettext` (paquete Alpine) por
  el binario `envsubst` — verificado explícitamente en vez de asumir que la imagen `nginx`
  upstream ya lo trae.
- **`config.js` nunca debe cachearse agresivamente.** `default.conf` le pone
  `Cache-Control: no-store`; para el caso CloudFront/S3 hay que replicar esa política a mano (ver
  `docs/07-operations.md`) o un cambio de configuración no se notaría hasta expirar la caché del
  CDN/navegador.
- **`envsubst` no escapa sus valores.** `CAPATAZ_FRONTEND_*` son config operativa (URLs, un scope,
  un booleano), nunca input de usuario final, pero ninguna debe contener `"` ni `\` — rompería el
  JS generado. Documentado en el propio script de entrypoint.
- **`VITE_DEV_USER` (identidad determinista de `dev_mock` en desarrollo) pasa a `DEV_USER`**, con
  el mismo tratamiento que el resto de campos: expuesto como `CAPATAZ_FRONTEND_DEV_USER` en
  `docker-compose.yml`/`frontend/Makefile`/`.env.example`, con default `ana.admin`, y presente en
  `frontend/public/config.js`. Útil para pruebas deterministas (p. ej. e2e) que necesiten una
  identidad fija en modo `dev_mock` sin tocar el selector de rol del menú.
- **Tests:** `Oidc.spec.ts` pasa de `vi.stubEnv('VITE_OIDC_ISSUER', …)` a fijar
  `window.__APP_CONFIG__` antes de `vi.resetModules()` — mismo patrón, distinta fuente. Nuevo
  `RuntimeConfig.spec.ts` cubre defaults, overrides parciales, coerción de `USE_MSW` (booleano real
  vs. string) y el caso de `config.js` ausente. El renderizado Docker (`envsubst` + `read_only` +
  tmpfs) se verificó manualmente construyendo la imagen y arrancándola con `--read-only`; no hay
  test automatizado de shell en este repo para ese script.
- **Documentación:** todas las menciones a `VITE_*`/"baked at build time" en `CLAUDE.md`,
  `docs/02-contracts.md`, `docs/08-debugging.md`, `docs/09-authentik-oidc-setup.md`,
  `docs/10-cognito-oidc-setup.md`, `frontend/README.md` y las cadenas i18n `errors.oidc.notConfigured`
  (8 locales) se actualizaron a `CAPATAZ_FRONTEND_*`/`config.js`. `docs/14-frontend-build-notes.md`
  es una nota fechada de una validación puntual (2026-08-08) y se deja tal cual, como registro
  histórico.

## Alternativas consideradas

- **Mantener `--build-arg`, documentar "un build por entorno".** Es lo que se pedía evitar
  explícitamente — no cumple el requisito de "un paquete, cualquier entorno".
- **Endpoint de configuración servido por la propia API** (`GET /api/v1/frontend-config` o
  similar): evita un fichero estático que sincronizar, pero añade una llamada de red bloqueante
  antes de poder pintar nada (incluida la pantalla de login), y un nuevo endpoint público sin
  autenticar en la superficie de la API — el proyecto ya evita deliberadamente superficie
  innecesaria (`CLAUDE.md`). `config.js` no tiene ese coste: se carga en paralelo/antes del bundle,
  sin round-trip adicional percibido por el usuario.
- **`.env` real leído por Nginx via `envsubst` en el propio `index.html`** (en vez de un
  `config.js` separado): mezclar la plantilla con el punto de entrada de la SPA complica servirlo
  igual en el caso estático (S3/CloudFront no ejecuta `envsubst`); un `config.js` aparte es un
  fichero más simple de sustituir a mano.
- **Variable global inyectada por un script inline en `index.html` con placeholders tipo
  `__RUNTIME_API_BASE_URL__`** sustituidos por `sed`: funcionalmente equivalente a `envsubst`
  sobre `config.js`, pero reinventa una herramienta (`envsubst`) que la propia imagen base de
  Nginx ya usa y documenta para este patrón exacto.
