from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from capataz_api.application.policies import ContainerObservation, aggregate_status
from capataz_api.application.ports import ConnectorClientFactory
from capataz_api.application.services.connector_resolver import ConnectorResolver
from capataz_api.domain.entities import Service
from capataz_api.domain.exceptions import DomainError
from capataz_api.domain.specs import MetricSpec
from capataz_api.domain.value_objects import AggregationMode


class StatusService:
    def __init__(self, factory: ConnectorClientFactory) -> None:
        self.factory = factory

    async def refresh(self, service: Service, resolver: ConnectorResolver) -> dict[str, Any]:
        log = logger.bind(service_id=service.id)
        spec = service.spec
        available = True
        rows: list[dict[str, Any]] = []
        external: bool | None = None
        errors: list[str] = []
        runtime = spec.runtime
        if runtime is not None:
            try:
                connector = await resolver.get(runtime.connector)
                platform = self.factory.platform(connector, await resolver.secrets_for(connector))
                rows = await platform.container_states(
                    runtime.environment_id, runtime.platform_selectors()
                )
            except DomainError as exc:
                available = False
                errors.append(str(exc))
                log.warning(f"Runtime status check failed: {exc}")
            except Exception:
                available = False
                errors.append("Unexpected error checking Portainer status")
                log.exception("Unexpected error checking Portainer status")
        health = spec.observability.health
        if health is not None:
            try:
                connector = await resolver.get(health.connector)
                prober = self.factory.prober(connector)
                external = await prober.probe(health.model_dump(mode="json"))
            except DomainError as exc:
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
            spec.maintenance,
            available,
            runtime.aggregation if runtime else AggregationMode.ALL_REQUIRED,
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
        if spec.observability.metrics:
            result["metrics"] = await self._metrics(
                service.id, spec.observability.metrics, resolver
            )
        return result

    async def _metrics(
        self, service_id: str, metrics: list[MetricSpec], resolver: ConnectorResolver
    ) -> list[dict[str, Any]]:
        """One provider call per connector, in declaration order; a failing connector only
        blanks its own metrics (value None) — metrics are informational and must never hide
        the status/containers/health already computed."""
        values: dict[int, Any] = {}
        by_connector: dict[str, list[int]] = defaultdict(list)
        for index, metric in enumerate(metrics):
            by_connector[metric.connector].append(index)
        for connector_id, indexes in by_connector.items():
            try:
                connector = await resolver.get(connector_id)
                provider = self.factory.metrics(connector, await resolver.secrets_for(connector))
                results = await provider.query(
                    [{"label": metrics[i].label, "query": metrics[i].query} for i in indexes]
                )
                for index, item in zip(indexes, results, strict=True):
                    values[index] = item.get("value")
            except Exception:
                logger.bind(service_id=service_id).exception(
                    f"Unexpected error querying metrics through connector {connector_id!r}"
                )
        return [{"label": metric.label, "value": values.get(i)} for i, metric in enumerate(metrics)]
