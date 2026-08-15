from dataclasses import dataclass

from capataz_api.domain.value_objects import AggregationMode, ServiceStatus


@dataclass(frozen=True, slots=True)
class ContainerObservation:
    running: bool
    healthy: bool | None = None
    required: bool = True
    critical: bool = False


def aggregate_status(
    containers: list[ContainerObservation] | None,
    external_healthy: bool | None,
    maintenance: bool = False,
    integration_available: bool = True,
    aggregation: AggregationMode | str = AggregationMode.ALL_REQUIRED,
) -> ServiceStatus:
    aggregation = AggregationMode(aggregation)
    if maintenance:
        return ServiceStatus.MAINTENANCE
    if not integration_available or (not containers and external_healthy is None):
        return ServiceStatus.UNKNOWN
    observed = containers or []
    required = [item for item in observed if item.required]
    critical = [item for item in observed if item.critical]
    if _is_down(observed, required, critical, external_healthy, aggregation):
        return ServiceStatus.DOWN
    if _is_healthy_via_any(observed, external_healthy, aggregation):
        return ServiceStatus.HEALTHY
    if _is_degraded(observed, required, external_healthy):
        return ServiceStatus.DEGRADED
    if _is_healthy_via_all_required(required, external_healthy):
        return ServiceStatus.HEALTHY
    return ServiceStatus.UNKNOWN


def _is_down(
    observed: list[ContainerObservation],
    required: list[ContainerObservation],
    critical: list[ContainerObservation],
    external_healthy: bool | None,
    aggregation: AggregationMode,
) -> bool:
    if critical and any(not item.running for item in critical):
        return True
    if external_healthy is False and (not observed or aggregation == AggregationMode.ALL_REQUIRED):
        return True
    # Only all_required treats "every required container is down" as an immediate DOWN — with
    # any_healthy, a healthy non-required container below can still bring the service back to
    # HEALTHY (see docs/05-yaml-catalog.en.md); this used to fire unconditionally (CR-007).
    return (
        aggregation == AggregationMode.ALL_REQUIRED
        and bool(required)
        and not any(item.running for item in required)
    )


def _is_healthy_via_any(
    observed: list[ContainerObservation],
    external_healthy: bool | None,
    aggregation: AggregationMode,
) -> bool:
    return (
        aggregation == AggregationMode.ANY_HEALTHY
        and bool(observed)
        and any(item.running and item.healthy is not False for item in observed)
        and external_healthy is not False
    )


def _is_degraded(
    observed: list[ContainerObservation],
    required: list[ContainerObservation],
    external_healthy: bool | None,
) -> bool:
    return (
        any(not item.running for item in required)
        or any(item.healthy is False for item in observed)
        or external_healthy is False
    )


def _is_healthy_via_all_required(
    required: list[ContainerObservation], external_healthy: bool | None
) -> bool:
    all_required_running = not required or all(item.running for item in required)
    return all_required_running and external_healthy is not False
