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
| `cognito_client_secret` | api | Integración Cognito. |
| `resources_master_key` | api, runner | Clave(s) Fernet que cifran los recursos del catálogo; la primera línea cifra, todas descifran (rotación). |

Todos se inyectan como ficheros `/run/secrets/*`, en modo lectura y solo al consumidor necesario. No están en Git, `.env`, YAML, parámetros, logs, excepciones, snapshots ni respuestas. Crea ficheros con `umask 077`, aplica `chmod 600`, rota ante sospecha y reinicia consumidores. Sanitiza logs con patrones de token, clave privada, bearer, password y Vault antes de persistir `ExecutionEvent`.

## Recursos del catálogo (credenciales de integración cifradas)

Los tokens de Portainer/Prometheus, las claves privadas SSH, los `known_hosts` y las contraseñas de Ansible Vault ya no son Docker secrets: son **recursos** del catálogo ([ADR 008](adr/008-connectors-and-resources.es.md)), referenciados por conectores.

- **En reposo:** se cifran con MultiFernet y `resources_master_key` antes de guardarse en PostgreSQL; un volcado de la base de datos por sí solo no los revela. Lo que detecta contenido sin cambios es una huella HMAC-SHA256 con clave (nunca un hash plano, que permitiría adivinar tokens de baja entropía).
- **Nunca se devuelven:** la API expone solo metadatos (tipo, tamaño, huella de 12 caracteres, procedencia, versión); la auditoría nunca incluye el contenido; la exportación del catálogo tampoco.
- **Orígenes de carga:** `{file: nombre}` está confinado a `CAPATAZ_RESOURCES_DIR` por `realpath` (sin `..`, sin symlinks que escapen, 64 KiB como máximo), para que un admin no pueda importar `/run/secrets/database_url` como recurso — mantén ese directorio (`./resources` en Compose) separado de `./secrets`. `{env: VAR}` lee el entorno de la API. `{base64: ...}` en el propio YAML es solo para desarrollo: genera un aviso y se rechaza con `CAPATAZ_ENV=production` salvo que `CAPATAZ_ALLOW_INLINE_RESOURCES=true`.
- **Uso:** la API descifra solo lo que usa ella misma (tokens de Portainer/Prometheus para estado y métricas). El runner descifra las credenciales de una acción justo antes de ejecutarla, las mantiene en memoria, añade cada valor descifrado a su lista de redacción y solo escribe material de claves en un directorio temporal `0700` por ejecución (ficheros `0600`) que se borra al terminar — también si falla o agota el tiempo.
- **Límite:** un admin puede hacer que un conector *use* cualquier recurso, pero nunca leerlo, y los conectores solo alcanzan hosts dentro de la allow-list global de sufijos (ver SSRF más abajo), así que un recurso no se puede dirigir a un destino arbitrario. Por eso `resources_master_key` es el secreto más sensible del despliegue: perderlo obliga a volver a subir todos los recursos, y filtrarlo junto con un volcado de la base de datos los expone todos.

## RBAC y confirmación

`viewer < operator < admin`. Viewer solo lee; operator ejecuta acciones `read` y `operate`; admin añade CRUD, catálogo, auditoría y `critical`. El backend decide con la definición persistida, no con información del navegador. Para `critical` exige confirmación explícita y motivo obligatorio. Todo cambio registra actor, acción, recurso, source, resultado, IP/request ID cuando esté disponible.

## Política allow-list

Una definición de servicio selecciona nombres de contenedor/servicio Swarm en su `runtime`, no IDs aportados por cliente. Acciones Portainer limitan `operation` a `start`, `stop`, `restart` o `logs`; Ansible limita playbook, limit, extra-vars y timeout a valores versionados/validados, y su inventario (del conector) al allow-list del runner; las acciones SSH solo eligen un `command_id` de `runner/ssh_commands.yml`, versionado, cuyos marcadores de argv ocupan elementos enteros y cuyos parámetros deben cumplir un `pattern`/`enum` — además, el comando remoto se entrecomilla elemento a elemento, porque el lado remoto siempre lo pasa por la shell de login. No existe `shell=True`, `command`, path externo, URL de ejecución ni interpolación de argumentos del usuario. El worker vuelve a cargar la definición (acción, conector, recursos) de base de datos y la cola solo traslada un UUID.

**Riesgo residual conocido — logs de Portainer (acción `logs`):** `sanitize_text` redacta patrones de secreto *conocidos* (bearer/`password:`/x-api-key/vault) antes de persistir la salida de `docker logs` como `ExecutionEvent`, pero esa salida proviene de contenedores de terceros que Capataz no controla — si un servicio logea un secreto en un formato no reconocido por el regex (p. ej. `DB_PASS=hunter2`), quedaría persistido casi sin redactar en la tabla de auditoría/SSE de Capataz. No hay mitigación adicional hoy; si esto preocupa para un servicio concreto, restringe la acción `logs` de ese servicio a un `risk_level` más alto en el catálogo, o evita declarar la acción `logs` para servicios que sabes que logean datos sensibles en texto plano.

## Métricas del catálogo (límite de confianza de PromQL)

`metrics[].query` (docs/05-yaml-catalog.md) es el único campo del catálogo que lleva texto libre ejecutado contra un sistema externo — PromQL completo, sin validar forma ni contenido más allá de un límite de longitud, a diferencia de cualquier otro punto de integración anterior. Esto es intencionado, no una excepción a la política allow-list: la query la escribe quien pueda editar el catálogo (solo `capataz-admin`, protegido por el mismo RBAC que cualquier otra mutación del catálogo), nunca se deriva de una petición de ejecución, de un rol de menor privilegio ni de ningún otro input recibido en tiempo de petición. Está al mismo nivel de confianza que `health.url` o la ruta de un playbook de Ansible — configuración declarada por el operador, no input de cliente — y PromQL en sí es de solo lectura contra Prometheus (sin capacidad de mutación), acotado por `CAPATAZ_HTTP_TIMEOUT_SECONDS`, y nunca se plantilla ni se concatena con nada más antes de enviarse. Si este Prometheus llegase a compartirse con una audiencia de menor confianza, trata el acceso de edición del catálogo (`capataz-admin`) como el límite que lo protege — igual que hoy tratarías la autoría de playbooks de Ansible.

## Docker socket

Montar `/var/run/docker.sock` equivale normalmente a conceder control muy amplio sobre el host Docker y, por extensión, posible root en host. Por ello API no monta el socket y la V1 se integra con Portainer usando token mínimo. Si V2 necesita crear jobs, se evaluará un Docker socket proxy con endpoints allow-listed y autenticación mutua, o Kubernetes Jobs; consulta el diseño de runner efímero. No conviertas el socket en un atajo para depurar.

## SSH, sudo y Ansible

La clave pertenece a una cuenta de automatización, sin login humano ni reutilización, con acceso por host limitado en `authorized_keys`. `known_hosts` se fija por huella; no desactives comprobación de clave (el runner siempre pasa `StrictHostKeyChecking=yes`, y `BatchMode=yes` para los conectores `ssh`). Da `sudo` por comando/tarea imprescindible, no `NOPASSWD: ALL`. Playbooks, inventarios y `ssh_commands.yml` son versionados y se empaquetan como solo lectura. El Vault se usa para secretos de automatización, pero no sustituye Docker Secrets para credenciales del control plane. Para la clave de un conector `ssh`, fija además lo que puede ejecutar con un `command=`/`restrict` forzado en el `authorized_keys` del destino cuando sea viable — defensa en profundidad sobre la allow-list.

**Aprovisionamiento manual de la clave (fuera del alcance del repo):** Capataz nunca genera ni distribuye estos pares de claves — solo consume la mitad privada desde un recurso `ssh_private_key` referenciado por un conector `ansible` o `ssh` (campo `private_key`). El aprovisionamiento y la rotación son un procedimiento manual del operador, ejecutado fuera del repo, cada vez que se añade un nodo nuevo al homelab o rota la clave:

1. Genera un par de claves ed25519 en un puesto de administración de confianza — nunca en el host del runner ni en CI:
   ```
   ssh-keygen -t ed25519 -C "capataz-automation" -f ./runner_ssh_private_key -N ""
   ```
   Sin passphrase (`-N ""`): el runner usa la clave de forma desatendida, así que la capa de protección es el cifrado del recurso (y el fichero `0600` por ejecución que materializa), no un prompt de passphrase.
2. Sube la mitad privada como recurso `ssh_private_key` — **Catálogo → Recursos → Nuevo recurso** en la UI, o un recurso del catálogo con `source: {file: runner_ssh_private_key}` colocado en `CAPATAZ_RESOURCES_DIR` (`./resources/`, ignorado por git) — y referéncialo desde el `private_key` del conector.
3. Añade la mitad pública (`runner_ssh_private_key.pub`) a `~capataz_automation/.ssh/authorized_keys` en cada nodo listado en `runner/inventories/*.yml` (la cuenta es `ansible_user: capataz_automation`), idealmente restringida con un prefijo `from="<CIDR del homelab>"`, ya que esta cuenta solo debería ser alcanzable desde el host del runner.
4. Fija las claves de host: desde el host del runner (o un punto de vista equivalente en la red del homelab), ejecuta `ssh-keyscan` contra cada host del inventario, verifica cada huella por un canal fuera de banda (consola, IPMI, u otro canal ya de confianza — no la misma ruta de red que intentas verificar), y guarda el resultado como recurso `known_hosts` referenciado por el `known_hosts` del conector.
5. Borra de forma segura la copia local del material de clave privada en el puesto de administración (y de `./resources/`, si se importó desde fichero) una vez guardada como recurso (p. ej. `shred -u`) — no debe quedar ninguna copia en claro permanente.
6. Rota repitiendo los pasos 1-5 con un par de claves nuevo, sustituyendo el contenido del recurso (**Reemplazar contenido**, sin reinicios), verificando conectividad y solo entonces eliminando la clave pública antigua del `authorized_keys` de cada nodo.

## SSRF y health probes

En import/CRUD se permiten solo `http` y `https`, se resuelve y valida el destino antes de conectar, se deniegan loopback, link-local, RFC1918/metadata cloud salvo allow-list explícita de homelab, se impiden redirects a destinos nuevos y se imponen timeouts cortos. El endpoint de refresh recibe un ID de servicio, nunca una URL. Las respuestas no deben reflejar cuerpos remotos sensibles.

Las mismas reglas cubren todo destino saliente que pueda declarar un catálogo, no solo los health checks: las URLs de conectores (Portainer, Prometheus, Grafana, Loki) y los hosts SSH se validan contra `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` (`application/policies/outbound_urls.py`), que es el techo global — el `allowed_host_suffixes` de un conector `http` solo puede restringirlo, nunca ampliarlo. Las URLs de Portainer tienen que ser `https`, porque el token viaja en cada petición.

**Riesgo residual conocido — DNS rebinding:** `validate_outbound_url` valida la cadena de hostname contra el allow-list de sufijos, pero no resuelve ni fija la IP a la que `httpx` acaba conectando — un hostname permitido por sufijo cuyo DNS interno resuelva (en el momento de la petición) a una IP privada/loopback/metadata no prevista pasaría la validación. Se acepta como riesgo bajo dado el modelo de confianza cerrado del homelab (el DNS que resuelve `.404labo.net` es propiedad del operador), pero es una brecha real frente al requisito literal de SSRF si ese límite de confianza cambia alguna vez.

## Endurecimiento operativo

La red `internal` no publica bases de datos/broker; los contenedores emplean filesystem read-only cuando pueden, tmpfs temporal, `cap_drop: ALL`, `no-new-privileges` y límites de CPU/memoria. Mantén imágenes fijadas, actualizadas y analizadas con Trivy; usa Dependabot y gitleaks. Revisa periódicamente tokens Portainer, grupos Cognito, inventarios, registros de auditoría y restauraciones de backup.

**Nota de diseño — sin TLS interno:** `postgresql+asyncpg://`/`redis://` (API y runner) no usan TLS entre servicios; se acepta hoy porque toda la comunicación ocurre dentro de la red Docker `internal`, no expuesta. Si el modelo de despliegue cambiara (p. ej. Postgres/Redis en un host distinto sin red de confianza compartida), habría que añadir soporte `sslmode`/`rediss://` parametrizable antes de exponer esas conexiones fuera de una red aislada.
