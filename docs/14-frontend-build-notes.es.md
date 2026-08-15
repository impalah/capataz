# Notas de construcción — Capataz frontend

*Idioma: **Español** · [English](14-frontend-build-notes.en.md)*

> Esta nota se actualiza al finalizar la validación. Consulte las salidas de comandos en el historial de construcción si necesita el detalle de una incidencia.

## Implementado

- SPA Vue 3 / Quasar 2 con TypeScript estricto, Composition API, Pinia y Vue Router.
- Cliente `fetch` tipado en `src/api/`: URL base `/api/v1`, `X-Request-ID`, tratamiento explícito de 401/403 y cabeceras exactas de desarrollo `X-Dev-User` / `X-Dev-Groups`.
- Tipos de dominio alineados a `docs/02-contracts.md`: estados, riesgos, tipos de acción, roles, ejecuciones, eventos y auditoría. `README.md` documenta la futura generación desde OpenAPI.
- Stores `useAuthStore`, `useServicesStore` y `useExecutionsStore`; selector dev_mock de roles para pruebas deterministas.
- Dashboard filtrable con estados loading/error/empty, detalle de servicio, acciones con confirmación/motivo obligatorio para `critical`, historial QTable, ejecución con timeline/SSE, catálogo con CRUD de servicio y alta de acciones, YAML dry-run/import/export, y auditoría protegida para admin.
- `VITE_USE_MSW=true` activa un modo sin login: usuario sintético con selector de rol (viewer/operator/admin) que llama a la API real vía `CAPATAZ_AUTH_MODE=dev_mock` — no hay mocks en el navegador, la SPA siempre habla con el backend real. Se desactiva con `VITE_USE_MSW=false` para probar login OIDC/Cognito real.
- Docker multi-stage sin secretos. Nginx no root recibe en 80; `/api/` hace proxy a `api:8000`, incluido soporte para SSE.

## Validación ejecutada

Los siguientes comandos se ejecutaron desde este directorio el 2026-08-08:

| Comando | Resultado |
|---|---|
| `npm install` | Correcto; npm informó 3 vulnerabilidades transitivas (2 high, 1 critical), sin aplicar una actualización potencialmente rompiente. |
| `npm run lint` | Correcto. |
| `npm run typecheck` | Correcto (`vue-tsc --noEmit`). |
| `npm run test:unit` | Correcto: 4 ficheros, 10 tests; cobertura de las unidades incluidas: 100% statements/líneas, 87.87% branches, 80% functions. |
| `npm run build` | Correcto; bundle Vite de producción generado en `dist/`. |
| `npx playwright install --with-deps chromium` | Correcto; Chromium y dependencias instalados en el sandbox. |
| `npm run e2e` | Correcto: 2 tests Chromium. Cubre flujo admin (servicios, detalle, confirmación crítica, ejecución, import YAML) y visibilidad viewer. |

Una primera invocación literal de `npm run test:unit -- --coverage` duplicó `--coverage` porque el script ya lo lleva; la ejecución equivalente correcta fue `npm run test:unit` y es la registrada en la tabla. Durante el bootstrap se intentó `npm install` desde el directorio de trabajo global; se corrigió ejecutándolo con el prefijo del subproyecto, sin modificar nada fuera de `frontend/`.

## Decisiones y límites V1

- `ExecutionPage.vue` sondea `GET /executions/{id}` + `GET /executions/{id}/events` cada 3s mientras la ejecución no sea terminal, en vez de usar el endpoint SSE `GET /executions/{id}/events/stream` — `EventSource` no permite adjuntar cabeceras (ni `Authorization: Bearer` ni `X-Dev-User`/`X-Dev-Groups`), así que ese endpoint solo se podía autenticar bajo `dev_mock`. El endpoint sigue existiendo (autenticado, usable por consumidores de la API que sí puedan adjuntar cabecera), pero el frontend ya no lo llama.
- La UI usa los claims para ergonomía, pero la API vuelve a autorizar mutaciones. Las respuestas 403 se presentan sin detalles internos.
- El formulario de acciones mantiene una configuración declarativa mínima; no expone campos para comandos, URLs arbitrarias ni playbooks arbitrarios.
- No se construyó la imagen Docker en este sandbox porque no se ha asumido disponibilidad de daemon Docker. El build de producción de la SPA sí pasó; el Dockerfile usa `npm ci`, por lo que consume el `package-lock.json` generado.
