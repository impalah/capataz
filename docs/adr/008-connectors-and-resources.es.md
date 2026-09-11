# ADR 008: Conectores y recursos cifrados (catálogo v2)

*Idioma: [English](008-connectors-and-resources.en.md) · **Español***

- **Estado:** Aceptada
- **Fecha:** 2026-09-11
- **Sustituye parcialmente a:** [ADR 003](003-secrets-and-credentials.es.md) (solo las credenciales de acciones)

## Contexto

Hasta el catálogo v1, cada integración tenía exactamente **una** identidad global: las URLs de
Portainer, Grafana, Loki y Prometheus eran variables de entorno `CAPATAZ_*_URL`, y el token de
Portainer, la clave SSH del runner, su `known_hosts` y la contraseña de Ansible Vault eran Docker
secrets fijos. Cada servicio incrustaba su propia configuración de Portainer/health/Grafana/Loki/
métricas. En consecuencia:

- No podían convivir dos Portainer, dos claves SSH o un host con credenciales distintas.
- Añadir un campo o un tipo de integración obligaba a tocar ~8 capas (esquema, DTO, ORM,
  repositorio, políticas, runner, frontend, docs) — el punto 11 del roadmap.
- Las credenciales solo podía cambiarlas un operador con acceso a los hosts (un Docker secret nuevo
  y un redespliegue), nunca desde la aplicación.

## Decisión

Un modelo de tres capas, declarado entero en **un único fichero de catálogo** (`version: 2`) y
editable también desde la API/UI:

1. **Recursos** — ficheros y secretos (`secret`, `ssh_private_key`, `known_hosts`, `file`)
   guardados **cifrados en PostgreSQL**. La API nunca devuelve su contenido, solo metadatos (tipo,
   tamaño, huella corta, procedencia, versión).
2. **Conectores** — plugins de conexión tipados (`portainer`, `prometheus`, `grafana`, `loki`,
   `http`, `ansible`, `ssh`). Cada tipo es un modelo Pydantic de configuración (una unión
   discriminada por `type`) que declara sus **capacidades** (`status`, `actions`, `metrics`,
   `health`, `dashboards`, `logs`) y qué campos suyos referencian un recurso, y de qué tipo.
3. **Servicios** — un `spec` JSON (runtime, observabilidad, tags...) que referencia conectores por
   capacidad; cada acción referencia un conector con la capacidad `actions`, y su `config` se valida
   con el modelo de acción del tipo de ese conector.

Reglas clave:

- **Origen de los recursos en el YAML.** `{file: nombre}` se lee de `CAPATAZ_RESOURCES_DIR` (por
  defecto `/run/capataz-resources`), confinado por `realpath` (sin `..` ni symlinks que escapen) y
  con un límite de 64 KiB — si no, un admin podría importar `/run/secrets/database_url` como
  recurso. `{env: VAR, encoding: plain|base64}` lee una variable de entorno del proceso de la API.
  `{base64: ...}` es un literal en el propio YAML, solo para desarrollo/pruebas: la importación
  devuelve un aviso y **se rechaza con `CAPATAZ_ENV=production`** salvo que
  `CAPATAZ_ALLOW_INLINE_RESOURCES=true`. Sin `source`, el recurso tiene que existir ya en la base de
  datos (subido desde la UI). La exportación nunca incluye contenido.
- **Cifrado.** MultiFernet de `cryptography` con el Docker secret `resources_master_key`: una clave
  por línea, la primera cifra y todas descifran, lo que permite rotarla. Una huella HMAC-SHA256 con
  clave (no un SHA plano, que permitiría adivinar tokens de baja entropía) detecta contenido sin
  cambios al reimportar.
- **Quién descifra.** La API, solo lo que usa ella misma (tokens de Portainer/Prometheus para estado
  y métricas). El runner, las credenciales de las acciones, con su propia copia del cifrado que solo
  descifra (ambas suites prueban un vector compartido). **Por la cola sigue viajando solo
  `execution_id`**: el runner relee acción, conector y recursos de PostgreSQL, descifra en memoria y
  solo escribe material de claves en un directorio temporal `0700` por ejecución (ficheros `0600`)
  que se borra al terminar.
- **SSH con allow-list.** Una acción `ssh` lleva `command_id` + `params` validados, nunca texto: los
  comandos viven en `runner/ssh_commands.yml`, versionado (argv con marcadores `{param}` que ocupan
  el elemento entero, `pattern`/`enum` por parámetro y timeout por comando). El comando remoto se
  entrecomilla elemento a elemento; `BatchMode=yes`, `StrictHostKeyChecking=yes` y `known_hosts`
  fijado. La clave `command` sigue prohibida en todas partes.
- **SSRF.** `CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` es el techo global de toda URL saliente: health
  checks, URLs de conectores y hosts SSH. El `allowed_host_suffixes` de un conector `http` solo
  puede restringirlo, nunca ampliarlo. Las URLs de Portainer tienen que ser `https` (el token viaja
  en cada petición).
- **Persistencia.** `services.spec` (JSONB) más las columnas desnormalizadas `name`/`group_name`/
  `environment` para los filtros SQL; tablas nuevas `resources` y `connectors`;
  `action_definitions.connector_id` es una clave foránea con `ON DELETE RESTRICT`. La migración
  `0009` convierte las filas v1 creando conectores provisionales a partir de las antiguas variables
  `CAPATAZ_*_URL`; es irreversible (antes, `pg_dump`). `scripts/convert_catalog_v1_to_v2.py`
  convierte un YAML v1.

## Consecuencias

- Pueden convivir varios Portainer, claves SSH o servidores Prometheus, y las credenciales se rotan
  desde la UI sin redesplegar nada.
- Un tipo de integración nuevo es un modelo de configuración más un adaptador; servicios, catálogo
  y UI lo incorporan a través de sus capacidades.
- `resources_master_key` pasa a ser el secreto más crítico del despliegue: perderlo obliga a volver
  a subir todos los recursos; filtrarlo junto con un volcado de la base de datos los expone todos.
  Solo se monta en `api` y `runner`.
- Un admin del catálogo puede hacer que un conector *use* cualquier recurso, pero nunca leerlo, y un
  conector solo alcanza hosts dentro del techo global de sufijos — no se puede exfiltrar un recurso
  a un destino arbitrario.
- La migración `0009` es de un solo sentido; volver atrás significa restaurar el volcado y las
  imágenes anteriores.
- El frontend refleja las allow-lists del runner (playbooks, inventarios, ids de comandos SSH) como
  constantes, igual que ya hacía con los playbooks; el runner sigue siendo la fuente de verdad.

## Alternativas consideradas

- **Un Docker secret por credencial, referenciado por nombre desde el conector** (la propuesta
  original del roadmap): mantiene los secretos fuera de la base de datos, pero añadir o rotar una
  credencial sigue requiriendo acceso al host y un redespliegue — justo la limitación que se quiere
  eliminar.
- **Gestor de secretos externo (Vault, AWS Secrets Manager):** mejor para despliegues grandes, pero
  una dependencia nueva y pesada para un homelab; el puerto `ResourceCipher` deja sitio para ello.
- **Comandos SSH de texto libre:** descartado — reintroduciría la ejecución remota arbitraria que el
  proyecto existe para evitar.
- **Recursos en claro en la base de datos:** descartado; cualquier volcado o backup filtraría todas
  las credenciales.

## Relación con ADR 003

ADR 003 sigue rigiendo `database_url`, `redis_url`, `postgres_password`, `redis_password`,
`cognito_client_secret` y el nuevo `resources_master_key`. Los Docker secrets `portainer_token`,
`prometheus_token`, `runner_ssh_private_key`, `runner_known_hosts` y `ansible_vault_password` se
sustituyen por recursos referenciados desde conectores.
