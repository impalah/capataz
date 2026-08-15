from datetime import UTC, datetime
from typing import Any

from loguru import logger

from capataz_api.application.policies import ContainerObservation, aggregate_status
from capataz_api.application.ports import ContainerPlatformPort, HealthProbePort, StatusCache
from capataz_api.domain.entities import Service
from capataz_api.domain.exceptions import ExternalServiceError


class StatusService:
    def __init__(
        self,
        cache: StatusCache,
        platform: ContainerPlatformPort | None,
        prober: HealthProbePort | None,
        ttl: int,
    ) -> None:
        self.cache, self.platform, self.prober, self.ttl = cache, platform, prober, ttl

    async def get(self, service: Service) -> dict[str, Any] | None:
        return await self.cache.get(service.id)

    async def refresh(self, service: Service) -> dict[str, Any]:
        log = logger.bind(service_id=service.id)
        available = True
        rows: list[dict[str, Any]] = []
        external: bool | None = None
        errors: list[str] = []
        if service.portainer_environment_id and self.platform:
            try:
                rows = await self.platform.container_states(
                    service.portainer_environment_id, service.container_selectors
                )
            except ExternalServiceError as exc:
                available = False
                errors.append(str(exc))
                log.warning(f"Portainer status check failed: {exc}")
            except Exception:
                available = False
                errors.append("Unexpected error checking Portainer status")
                log.exception("Unexpected error checking Portainer status")
        elif service.portainer_environment_id:
            available = False
        if service.health_config and self.prober:
            try:
                external = await self.prober.probe(service.health_config)
            except ExternalServiceError as exc:
                errors.append(str(exc))
                log.warning(f"Health probe failed: {exc}")
            except Exception:
                errors.append("Unexpected error checking service health")
                log.exception("Unexpected error checking service health")
        observations = [
            ContainerObservation(
                running=bool(row.get("running")),
                healthy=row.get("healthy"),
                required=bool(row.get("required", True)),
                critical=bool(row.get("critical", False)),
            )
            for row in rows
        ]
        status = aggregate_status(
            observations,
            external,
            service.maintenance,
            available,
            str(service.container_selectors.get("aggregation", "all_required")),
        )
        result: dict[str, Any] = {
            "service_id": service.id,
            "status": status.value,
            "checked_at": datetime.now(UTC).isoformat(),
            "containers": rows,
            "external_healthy": external,
        }
        if errors:
            result["error"] = "; ".join(errors)
        await self.cache.set(service.id, result, self.ttl)
        return result
