# ADR 002: Worker Celery persistente en V1

*Idioma: **Español** · [English](002-celery-persistent-worker-v1.en.md)*

- **Estado:** Aceptada
- **Fecha:** 2026-08-08

## Contexto

Las acciones pueden durar más que una petición HTTP y requieren reintentos, timeouts, eventos y acceso controlado a Ansible/SSH. Se necesita un mecanismo fiable y simple de operar desde el primer despliegue. A futuro puede interesar un contenedor efímero por ejecución para aumentar aislamiento.

## Decisión

V1 usa un servicio `runner` Celery persistente, sin puertos publicados, que consume la cola Redis `automation`. API persiste `Execution` y publica únicamente `{"execution_id":"<uuid>"}` en `capataz_runner.tasks.process_execution`. El runner reclama `queued -> running`, vuelve a cargar definición persistida y usa `PersistentWorkerAutomationExecutor`. Se aplican `acks_late`, límites de tiempo, concurrencia conservadora y eventos sanitizados.

## Consecuencias

- Operación sencilla con servicios conocidos y menos latencia de arranque.
- API no incorpora Ansible/SSH y el runner recibe solo los secretos necesarios.
- Los trabajos comparten un runtime persistente; exige disciplina de limpieza y límites.
- Se conserva `AutomationExecutorPort` para migrar a `EphemeralDockerAutomationExecutor` sin cambiar casos de uso.

## Alternativas consideradas

- **Ejecutar Ansible dentro de API:** rechazado por separación de responsabilidades, seguridad y latencia HTTP.
- **Docker job efímero desde el inicio:** mejor aislamiento, pero exige una solución segura para orquestar jobs y más operación; se diseña para V2.
- **Kubernetes Jobs:** apropiado para un futuro clúster, pero no es requisito del despliegue Compose V1.
