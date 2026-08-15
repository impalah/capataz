# ADR 003: Secretos como ficheros Docker y responsabilidad sobre las credenciales

*Idioma: **Español** · [English](003-secrets-and-credentials.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-08

## Contexto

Capataz necesita contraseñas PostgreSQL/Redis, token Portainer, secreto Cognito y material SSH/Ansible Vault. Variables de entorno, `.env`, catálogo YAML y repositorio aumentan el riesgo de filtración a procesos, logs, backups y control de versiones. API y runner no necesitan exactamente las mismas credenciales.

## Decisión

Los secretos se guardan como ficheros locales ignorados bajo `secrets/` y Compose los monta de solo lectura en `/run/secrets/<nombre>`. API los lee con `infrastructure/secrets/file_secret_reader.py`. `postgres_password` y `redis_password` llegan a sus servicios y a consumidores; `cognito_client_secret` solo a API; la clave SSH, known_hosts y Vault solo al runner. `portainer_token` llega a API para estado y al runner porque V1 ejecuta acciones allow-listed de Portainer directamente; se limita a mínimos permisos y se reevalúa al migrar de executor.

## Consecuencias

- Los secretos no viajan por Git, `.env`, YAML, cola, logs o respuestas API.
- La rotación se hace sustituyendo fichero y recreando consumidores, con permisos POSIX restrictivos.
- El formato fichero exige lectura explícita y pruebas; no se debe convertir a variable de entorno por comodidad.
- La duplicación limitada de token Portainer se compensa con privilegios mínimos y separación de API/runner.

## Alternativas consideradas

- **Variables de entorno:** sencillas, pero más expuestas a inspección/procesos/logs y contrarias al contrato.
- **Secret manager externo obligatorio:** deseable en despliegues mayores, pero añade dependencia inicial; el lector de secretos puede adaptarse en el futuro.
- **API ejecuta Portainer por cuenta del runner:** centraliza token pero rompe separación de ejecución y añade salto de red/contrato innecesario.

> Actualización (ver ADR-006): `postgres_password`/`redis_password` ya solo alimentan el bootstrap de
> los propios contenedores `postgres`/`redis`. `api`/`runner` reciben el DSN completo (password
> incluido) como un único secreto — `database_url`/`redis_url` — en vez de ensamblarlo desde variables
> `CAPATAZ_POSTGRES_*`/`CAPATAZ_REDIS_*` sueltas más el secreto de password.
