# Capataz Runner

*Idioma: **Español** · [English](README.md)*

Worker Celery de Capataz. Reclama ejecuciones por `execution_id`, relee `Service`/`ActionDefinition` desde PostgreSQL y ejecuta únicamente acciones Portainer/Ansible resueltas por el allow-list de `actions.py`.

## Seguridad

`actions.py::resolve_action` es el único punto de resolución: tipos, playbooks, inventories y operaciones Portainer están restringidos a frozensets versionados. Ansible se invoca con `asyncio.create_subprocess_exec` (nunca shell), clave SSH y vault password leídos de `/run/secrets/*`.

## Desarrollo

```bash
make install
make test
```

Requiere PostgreSQL y Redis según las variables de [docs/02-contracts.md](../docs/02-contracts.es.md). Los secretos se leen únicamente de `/run/secrets/*`.
