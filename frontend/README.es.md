# Capataz frontend

*Idioma: **Español** · [English](README.md)*

SPA privada para consultar y operar el catálogo Capataz. Está construida con Vue 3, Quasar 2, TypeScript estricto, Pinia y Vue Router. El cliente lee su configuración en tiempo de ejecución de `config.js` (ver [ADR 007](../docs/adr/007-runtime-frontend-config.es.md)) — por defecto apunta a `http://localhost:8000/api/v1` —, genera un `X-Request-ID` por petición y, únicamente en modo `dev_mock`, transmite `X-Dev-User` y `X-Dev-Groups`.

## Desarrollo autónomo

```sh
npm install
npm run dev
```

Por defecto `public/config.js` activa el modo `dev_mock` (`USE_MSW: true`) y proporciona un usuario sintético con rol elegible desde el selector de la esquina superior (`capataz-viewer`/`capataz-operator`/`capataz-admin`) contra la API real (no hay mocks en el navegador — pese al nombre histórico del flag, nunca hubo Mock Service Worker; ver `CLAUDE.md`).

Para conectar una API real con login OIDC en vez de `dev_mock`, edita `public/config.js` directamente (`npm run dev` lo sirve tal cual desde disco, así que los cambios aplican al refrescar, sin rebuild): pon `USE_MSW: false` y rellena `OIDC_ISSUER`/`OIDC_CLIENT_ID`. La API sigue siendo la autoridad: ocultar un control en la UI nunca sustituye a sus reglas RBAC.

## Calidad

```sh
npm run lint
npm run typecheck
npm run test:unit
npm run build
npm run e2e
```

`npm run e2e:install` instala Chromium cuando el entorno no lo tenga. Consulta `docs/14-frontend-build-notes.es.md` para el resultado real de la última validación.

## Sincronización con OpenAPI

Los tipos de `src/api/types.ts` son el contrato manual de V1 y deben permanecer alineados con `/api/v1/openapi.json`. Cuando la API esté disponible:

```sh
API_BASE_URL=http://localhost:8000 npm run generate:openapi
```

El comando deja la salida en `src/api/openapi.generated.ts`; se revisa el diff y se mapean los DTOs al contrato de la aplicación. Esto evita que una regeneración automática cambie de forma silenciosa la UI.

## Contenedor

El `Dockerfile` es multi-stage, no incorpora secretos y sirve el bundle como usuario no root. Nginx escucha en el puerto interno 80 y realiza proxy de `/api/` al upstream contractual `api:8000`, con streaming sin buffering para SSE. Compose debe publicar `8080:80`. La imagen se construye una sola vez — `config.js` se renderiza en cada arranque del contenedor a partir de variables `CAPATAZ_FRONTEND_*` (ver [ADR 007](../docs/adr/007-runtime-frontend-config.es.md)), no hace falta reconstruir para cambiarlas.

Para desplegar `dist/` sin Docker (S3+CloudFront, Nginx propio), ver la sección "Despliegue standalone" de [docs/07-operations.es.md](../docs/07-operations.es.md#despliegue-standalone-del-frontend-s3cloudfront--nginx-propio).
