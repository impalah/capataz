# ADR 002: Persistent Celery Worker in V1

*Language: **English** · [Español](002-celery-persistent-worker-v1.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

Actions can take longer than an HTTP request and require retries, timeouts, events, and controlled access to Ansible/SSH. A reliable mechanism that is simple to operate from the first deployment is needed. In the future, an ephemeral per-execution container may be desirable to increase isolation.

## Decision

V1 uses a persistent Celery `runner` service, with no published ports, that consumes the Redis `automation` queue. The API persists `Execution` and publishes only `{"execution_id":"<uuid>"}` to `capataz_runner.tasks.process_execution`. The runner claims `queued -> running`, reloads the persisted definition, and uses `PersistentWorkerAutomationExecutor`. `acks_late`, time limits, conservative concurrency, and sanitized events are applied.

## Consequences

- Simple operation with well-known services and less startup latency.
- The API does not embed Ansible/SSH, and the runner only receives the secrets it needs.
- Jobs share a persistent runtime, requiring cleanup discipline and limits.
- `AutomationExecutorPort` is kept so we can migrate to `EphemeralDockerAutomationExecutor` without changing use cases.

## Alternatives Considered

- **Running Ansible inside the API:** rejected for separation of concerns, security, and HTTP latency.
- **Ephemeral Docker job from the start:** better isolation, but requires a secure solution for orchestrating jobs and more operational overhead; designed for V2.
- **Kubernetes Jobs:** appropriate for a future cluster, but not a requirement of the V1 Compose deployment.
