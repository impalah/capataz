# Seguridad

*Idioma: **Español** · [English](06-security.en.md)*

## Modelo de amenazas resumido

Capataz media entre un usuario autenticado y capacidades operativas potentes. Los riesgos principales son: escalada de privilegios por RBAC defectuoso, ejecución remota arbitraria, filtración de secretos, abuso SSRF de healthchecks, compromiso del runner/host Docker, manipulación de cola y pérdida de trazabilidad. La respuesta es deny-by-default: identidad verificable, mínimo privilegio, configuraciones declaradas y auditoría.

## Secretos y exposición mínima

| Secret | Consumidores | Propósito |
|---|---|---|
| `database_url` | api, runner | DSN completo de SQLAlchemy (password incluido); tratado como un único secreto, no ensamblado desde partes sueltas. |
| `redis_url` | api, runner | URL completa de Redis (password incluido); broker/result backend y cache. |
| `postgres_password` | postgres | Solo inicialización propia del contenedor. |
| `redis_password` | redis | Solo `--requirepass` propio del contenedor. |
| `portainer_token` | api, runner | Lectura/acciones allow-listed de plataforma. |
| `cognito_client_secret` | api | Integración Cognito. |
| `runner_ssh_private_key` | runner | Cuenta técnica de automatización. |
| `runner_known_hosts` | runner | Verificación de host SSH. |
| `ansible_vault_password` | runner | Secret de Ansible Vault. |

Todos se inyectan como ficheros `/run/secrets/*`, en modo lectura y solo al consumidor necesario. No están en Git, `.env`, YAML, parámetros, logs, excepciones, snapshots ni respuestas. Crea ficheros con `umask 077`, aplica `chmod 600`, rota ante sospecha y reinicia consumidores. Sanitiza logs con patrones de token, clave privada, bearer, password y Vault antes de persistir `ExecutionEvent`.

## RBAC y confirmación

`viewer < operator < admin`. Viewer solo lee; operator ejecuta acciones `read` y `operate`; admin añade CRUD, catálogo, auditoría y `critical`. El backend decide con la definición persistida, no con información del navegador. Para `critical` exige confirmación explícita y motivo obligatorio. Todo cambio registra actor, acción, recurso, source, resultado, IP/request ID cuando esté disponible.

## Política allow-list

Una definición de servicio selecciona nombres/labels de contenedor, no IDs aportados por cliente. Acciones Portainer limitan `operation` a `start`, `stop`, `restart` o `logs`; Ansible limita playbook, inventory, limit, extra-vars y timeout a valores versionados/validados. No existe `shell=True`, `command`, path externo, URL de ejecución ni interpolación de argumentos del usuario. El worker vuelve a cargar la definición de base de datos y la cola solo traslada un UUID.

**Riesgo residual conocido — logs de Portainer (acción `logs`):** `sanitize_text` redacta patrones de secreto *conocidos* (bearer/`password:`/x-api-key/vault) antes de persistir la salida de `docker logs` como `ExecutionEvent`, pero esa salida proviene de contenedores de terceros que Capataz no controla — si un servicio logea un secreto en un formato no reconocido por el regex (p. ej. `DB_PASS=hunter2`), quedaría persistido casi sin redactar en la tabla de auditoría/SSE de Capataz. No hay mitigación adicional hoy; si esto preocupa para un servicio concreto, restringe la acción `logs` de ese servicio a un `risk_level` más alto en el catálogo, o evita declarar la acción `logs` para servicios que sabes que logean datos sensibles en texto plano.

## Docker socket

Montar `/var/run/docker.sock` equivale normalmente a conceder control muy amplio sobre el host Docker y, por extensión, posible root en host. Por ello API no monta el socket y la V1 se integra con Portainer usando token mínimo. Si V2 necesita crear jobs, se evaluará un Docker socket proxy con endpoints allow-listed y autenticación mutua, o Kubernetes Jobs; consulta el diseño de runner efímero. No conviertas el socket en un atajo para depurar.

## SSH, sudo y Ansible

La clave pertenece a una cuenta de automatización, sin login humano ni reutilización, con acceso por host limitado en `authorized_keys`. `known_hosts` se fija por huella; no desactives comprobación de clave. Da `sudo` por comando/tarea imprescindible, no `NOPASSWD: ALL`. Playbooks e inventarios son versionados y se montan/empaquetan como solo lectura. El Vault se usa para secretos de automatización, pero no sustituye Docker Secrets para credenciales del control plane.

## SSRF y health probes

En import/CRUD se permiten solo `http` y `https`, se resuelve y valida el destino antes de conectar, se deniegan loopback, link-local, RFC1918/metadata cloud salvo allow-list explícita de homelab, se impiden redirects a destinos nuevos y se imponen timeouts cortos. El endpoint de refresh recibe un ID de servicio, nunca una URL. Las respuestas no deben reflejar cuerpos remotos sensibles.

**Riesgo residual conocido — DNS rebinding:** `validate_health_url` valida la cadena de hostname contra el allow-list de sufijos, pero no resuelve ni fija la IP a la que `httpx` acaba conectando — un hostname permitido por sufijo cuyo DNS interno resuelva (en el momento de la petición) a una IP privada/loopback/metadata no prevista pasaría la validación. Se acepta como riesgo bajo dado el modelo de confianza cerrado del homelab (el DNS que resuelve `.home.arpa` es propiedad del operador), pero es una brecha real frente al requisito literal de SSRF si ese límite de confianza cambia alguna vez.

## Endurecimiento operativo

La red `internal` no publica bases de datos/broker; los contenedores emplean filesystem read-only cuando pueden, tmpfs temporal, `cap_drop: ALL`, `no-new-privileges` y límites de CPU/memoria. Mantén imágenes fijadas, actualizadas y analizadas con Trivy; usa Dependabot y gitleaks. Revisa periódicamente tokens Portainer, grupos Cognito, inventarios, registros de auditoría y restauraciones de backup.

**Nota de diseño — sin TLS interno:** `postgresql+asyncpg://`/`redis://` (API y runner) no usan TLS entre servicios; se acepta hoy porque toda la comunicación ocurre dentro de la red Docker `internal`, no expuesta. Si el modelo de despliegue cambiara (p. ej. Postgres/Redis en un host distinto sin red de confianza compartida), habría que añadir soporte `sslmode`/`rediss://` parametrizable antes de exponer esas conexiones fuera de una red aislada.
