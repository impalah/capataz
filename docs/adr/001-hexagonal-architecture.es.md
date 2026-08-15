# ADR 001: Arquitectura hexagonal pragmática

*Idioma: **Español** · [English](001-hexagonal-architecture.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-08

## Contexto

Capataz combina API HTTP, autenticación Cognito, catálogo YAML, PostgreSQL async, Redis/Celery, Portainer, healthchecks y automatización Ansible. Es probable que cambien integraciones y la estrategia de ejecución. Acoplar rutas FastAPI a SQLAlchemy, Celery o clientes HTTP convertiría cambios de infraestructura en reescrituras de negocio y haría difícil probar la política allow-list.

## Decisión

Usar arquitectura hexagonal pragmática: `domain` no depende de frameworks; `application` expresa casos de uso y puertos `Protocol`; `adapters` traduce HTTP; `infrastructure` implementa repositorios e integraciones; `core` contiene configuración/transversales. Controllers no contienen lógica de negocio. Los casos de uso no importan FastAPI, SQLAlchemy, Celery ni `httpx` concretos.

## Consecuencias

- Las reglas RBAC, estados, importación y ejecución se prueban sin red/DB.
- Portainer, Cognito, Celery o executor pueden sustituirse detrás de puertos.
- Requiere DTOs, mapeos y disciplina para no filtrar tipos de framework hacia el dominio.
- No implica crear microservicios: V1 sigue teniendo frontend, API y runner como tres unidades de despliegue.

## Alternativas consideradas

- **Arquitectura por capas acoplada al framework:** menos ficheros iniciales, pero bloquea cambios de integrations y dificulta tests seguros.
- **Microservicios por integración:** añade despliegue, identidad y observabilidad sin beneficio proporcional en V1.
- **Clean Architecture estricta con abstracción para todo:** demasiado ceremonial para un homelab; se abstraen solo límites de infraestructura relevantes.
