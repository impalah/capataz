# Capataz runner — notas de construcción

*Idioma: **Español** · [English](15-runner-build-notes.en.md)*

## Alcance implementado

`runner/` es el worker Celery persistente de V1. Consume exclusivamente la cola `automation` y expone la tarea exacta `capataz_runner.tasks.process_execution`. El mensaje contiene solamente `execution_id`; la tarea reclama atómicamente la fila (`queued` → `running`) y vuelve a leer `services`, `action_definitions` y `executions` antes de ejecutar nada.

La aplicación usa `Settings` de Pydantic con variables no sensibles `CAPATAZ_*`. Las credenciales se leen de ficheros en `/run/secrets`: `database_url` y `redis_url` (DSN completo, password incluido — ver ADR-006), `portainer_token`, `runner_ssh_private_key`, `runner_known_hosts` y `ansible_vault_password`.

`CAPATAZ_SECRETS_DIR` existe únicamente como punto de inyección para tests; en el contenedor el valor por defecto es el montaje de Docker Secrets.

## Decisiones de integración

- **Modelos SQLAlchemy ligeros locales.** El API todavía no expone un paquete de modelos compartido en este checkout. El runner define mappings de solo acceso
  con los nombres contractuales `services`, `action_definitions`, `executions` y `execution_events`; no crea tablas ni contiene migraciones. La propiedad de esquema y Alembic sigue siendo de `api/`. Cuando exista un paquete de dominio compartido, estos mappings se pueden sustituir sin cambiar el puerto `AutomationExecutorPort`.
- **Portainer se llama desde runner.** Solo el runner recibe `portainer_token`, de modo que la API no puede ejecutar acciones. Antes de cada operación se consulta Portainer y los IDs de contenedor se resuelven únicamente por los selectores declarados en `Service`; ningún ID del cliente, de la cola o de parámetros de ejecución se acepta.
- **Ansible por `asyncio.create_subprocess_exec`.** Se invoca `ansible-playbook` con un vector de argumentos allow-listed, `cwd` bajo `/app`, entorno mínimo, timeout y sin `shell=True`. La dependencia `ansible-runner` está empaquetada para permitir la futura alternativa, pero V1 usa el ejecutable de `ansible-core` para mantener los límites de proceso explícitos.
- **Seguridad de entrega.** Celery usa `acks_late`, `task_reject_on_worker_lost`, prefetch de uno, límites soft/hard, reintento de publicación y concurrencia configurable (2 por defecto). El claim condicional hace inocua una segunda entrega una vez que la ejecución está en `running`.
- **Secretos y observabilidad.** Toda salida de proceso, resultado y `ExecutionEvent` pasa por el sanitizador recursivo antes de persistirse. Se enmascaran claves sensibles y patrones Bearer/X-API-Key/password/Ansible Vault, además de los valores secretos conocidos.

## Artefactos operativos

- Los playbooks versionados son `restart_service.yml`, `backup_service.yml` (simulación no destructiva) y `check_connectivity.yml`. Solo admiten sus variables declaradas.
- `inventories/homelab.yml` contiene hosts ficticios `node-ai-01` y `node-gpu-01`; `inventories/local.yml` sirve para el smoke local seguro.
- El Dockerfile es multi-stage con Python 3.14, `uv`, `ansible-core`, `ansible-runner`, `openssh-client`, `rsync` y `git`; ejecuta como UID 10001, no publica puertos ni instala/expone `sshd`.
- El Makefile proporciona instalación, tests, lint, tipos, cobertura, validación y ejecución local de playbooks, y construcción Docker.

## Validación ejecutada

Ejecutado desde `runner/` el 2026-08-08:

```text
uv sync --all-groups                         # correcto
uv run ruff check                            # All checks passed!
uv run mypy                                  # Success: no issues found in 10 source files
uv run pytest --cov                          # 23 passed, cobertura total 83.59%
make playbook-check                          # correcto: 3 playbooks
make playbook-local                          # correcto: 3 playbooks contra local-mock
```

El sandbox no dispone del binario Docker, por lo que `make build` (imagen Docker) no se ha podido ejecutar aquí. El Dockerfile queda listo para validarse en CI.

## Cobertura de integración para CI

Los tests presentes son unitarios/SQLite y validan el claim en carrera, los estados y eventos, el rehidratado de la ejecución, la allow-list, resultados de
Ansible, sanitización y la configuración Celery. En CI con servicios Docker se debe añadir una suite de integración contra PostgreSQL 16 y Redis 7 que ejecute
las migraciones de `api/`, publique la tarea real y compruebe persistencia y redelivery. Portainer y nodos SSH reales no deben formar parte de la suite por
defecto: se prueban con un transporte HTTP controlado y un perfil de smoke explícitamente autorizado.
