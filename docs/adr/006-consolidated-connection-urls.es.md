# ADR 006: DSN consolidado (`database_url`/`redis_url`) en lugar de partes sueltas

*Idioma: **Español** · [English](006-consolidated-connection-urls.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-14

## Contexto

`api` y `runner` configuraban la conexión a PostgreSQL y Redis con cuatro/tres variables `CAPATAZ_*`
sueltas (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `REDIS_HOST`, `REDIS_PORT`,
`REDIS_DB`) más los secretos `postgres_password`/`redis_password` (ver ADR-003), y cada servicio
ensamblaba el DSN en `Settings.database_url`/`Settings.redis_url`. Operar tantos parámetros repartidos
para un único destino de conexión resultaba poco práctico.

## Decisión

`api` y `runner` reciben ahora un único Docker secret por conexión — `database_url` y `redis_url` —
con el DSN completo (esquema, usuario, password, host, puerto y base de datos/índice). Igual que en
ADR-003, cualquier parámetro que contenga una credencial se trata en su totalidad como secreto: no se
reconstruye el DSN a partir de host/puerto/usuario en variables `CAPATAZ_*` más un secreto de solo
password. Los secretos `postgres_password`/`redis_password` se mantienen, pero exclusivamente para
el arranque de los propios contenedores `postgres`/`redis` (`POSTGRES_PASSWORD_FILE`, `--requirepass`);
`api`/`runner` ya no los leen directamente. El operador es responsable de que la contraseña embebida
en `database_url`/`redis_url` coincida con la de `postgres_password`/`redis_password`.

`CAPATAZ_POSTGRES_DB`/`CAPATAZ_POSTGRES_USER` se mantienen como variables no sensibles porque siguen
siendo necesarias para inicializar el contenedor `postgres`; `CAPATAZ_POSTGRES_HOST/PORT` y
`CAPATAZ_REDIS_HOST/PORT/DB` desaparecen por completo, ya que ningún consumidor los necesitaba fuera
del propio DSN.

## Consecuencias

- Un único parámetro operativo por conexión, en vez de 3-4 variables más un secreto de password.
- El runner sigue necesitando la contraseña "pelada" (no la URL entera) para redactarla del output de
  Ansible/tracebacks (`sanitization.py`); se extrae parseando `database_url`/`redis_url` en vez de
  leerse de un secreto de password aparte — mismo nivel de protección, una sola fuente de verdad.
- Rotar la contraseña exige actualizar dos ficheros consistentes entre sí (`postgres_password`/`redis_password`
  para el motor, `database_url`/`redis_url` para los consumidores), en vez de uno; se documenta en README.md.

## Alternativas consideradas

- **DSN completo vía variable de entorno `CAPATAZ_DATABASE_URL`** (como en otros servicios del homelab,
  p. ej. `apikey-service`): más simple, pero pondría la contraseña en `.env`/Compose interpolation,
  violando la regla de ADR-003 de nunca poner secretos fuera de `secrets/`.
- **DSN sin password + inyección de password en tiempo de ejecución**: mantiene un único parámetro
  "operativo" pero reintroduce la composición en dos piezas que este ADR busca eliminar.
