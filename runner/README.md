# Capataz Runner

*Language: **English** · [Español](README.es.md)*

Capataz's Celery worker. Claims executions by `execution_id`, re-reads `Service`/`ActionDefinition` from PostgreSQL, and executes only Portainer/Ansible actions resolved through the `actions.py` allow-list.

## Security

`actions.py::resolve_action` is the single resolution point: types, playbooks, inventories, and Portainer operations are restricted to versioned frozensets. Ansible is invoked with `asyncio.create_subprocess_exec` (never shell), with the SSH key and vault password read from `/run/secrets/*`.

## Development

```bash
make install
make test
```

Requires PostgreSQL and Redis per the variables in [docs/02-contracts.md](../docs/02-contracts.en.md). Secrets are read only from `/run/secrets/*`.
