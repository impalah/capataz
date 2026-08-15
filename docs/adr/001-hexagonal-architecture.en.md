# ADR 001: Pragmatic Hexagonal Architecture

*Language: **English** · [Español](001-hexagonal-architecture.es.md)*

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

Capataz combines an HTTP API, Cognito authentication, a YAML catalog, async PostgreSQL, Redis/Celery, Portainer, healthchecks, and Ansible automation. Integrations and the execution strategy are likely to change over time. Coupling FastAPI routes directly to SQLAlchemy, Celery, or HTTP clients would turn infrastructure changes into business-logic rewrites and make the allow-list policy hard to test.

## Decision

Use a pragmatic hexagonal architecture: `domain` has no framework dependencies; `application` expresses use cases and `Protocol` ports; `adapters` translates HTTP; `infrastructure` implements repositories and integrations; `core` holds configuration/cross-cutting concerns. Controllers contain no business logic. Use cases never import concrete FastAPI, SQLAlchemy, Celery, or `httpx` symbols.

## Consequences

- RBAC rules, statuses, import, and execution are tested without network/DB.
- Portainer, Cognito, Celery, or the executor can be swapped out behind ports.
- Requires DTOs, mappings, and discipline to avoid leaking framework types into the domain.
- Does not imply creating microservices: V1 still ships frontend, API, and runner as three deployment units.

## Alternatives Considered

- **Framework-coupled layered architecture:** fewer files upfront, but locks in integration changes and makes safe testing harder.
- **Microservices per integration:** adds deployment, identity, and observability overhead without proportional benefit in V1.
- **Strict Clean Architecture with abstraction for everything:** too ceremonial for a homelab; only the infrastructure boundaries that matter are abstracted.
