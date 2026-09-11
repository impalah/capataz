"""Catalog v2 document shape (docs/05-yaml-catalog): resources, connectors and services.

Structure and intra-document uniqueness are checked here; references to connectors/resources
that may also live only in the database are checked by the importer (application/services).
"""

from typing import Literal

from pydantic import Field, model_validator

from capataz_api.domain.specs import (
    SERVICE_ID_PATTERN,
    ActionSpec,
    ConnectorSpec,
    ResourceSpec,
    ServiceSpec,
    SpecModel,
)


class ServiceDefinition(ServiceSpec):
    id: str = Field(pattern=SERVICE_ID_PATTERN, max_length=128)
    actions: list[ActionSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_action_keys(self) -> ServiceDefinition:
        keys = [action.key for action in self.actions]
        if len(keys) != len(set(keys)):
            raise ValueError(f"action keys must be unique for {self.id}")
        return self

    def to_spec(self) -> ServiceSpec:
        return ServiceSpec.model_validate(self.model_dump(exclude={"id", "actions"}))


class Catalog(SpecModel):
    version: Literal[2]
    resources: list[ResourceSpec] = Field(default_factory=list)
    connectors: list[ConnectorSpec] = Field(default_factory=list)
    services: list[ServiceDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> Catalog:
        for kind, ids in (
            ("resource", [item.id for item in self.resources]),
            ("connector", [item.id for item in self.connectors]),
            ("service", [item.id for item in self.services]),
        ):
            duplicates = sorted({item for item in ids if ids.count(item) > 1})
            if duplicates:
                raise ValueError(f"duplicate {kind} ids: {', '.join(duplicates)}")
        return self
