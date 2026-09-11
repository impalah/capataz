"""Request-scoped connector lookup plus on-demand decryption of the resources they reference."""

from capataz_api.application.ports import ResourceCipher, ServiceRepository
from capataz_api.domain.entities import Connector
from capataz_api.domain.exceptions import ConfigurationError
from capataz_api.domain.specs import connector_resource_refs


class ConnectorResolver:
    def __init__(self, repo: ServiceRepository, cipher: ResourceCipher) -> None:
        self._repo, self._cipher = repo, cipher
        self._connectors: dict[str, Connector] = {}

    async def get(self, connector_id: str) -> Connector:
        if connector_id not in self._connectors:
            connector = await self._repo.get_connector(connector_id)
            if connector is None:
                raise ConfigurationError(f"Connector {connector_id!r} does not exist")
            self._connectors[connector_id] = connector
        return self._connectors[connector_id]

    async def secrets_for(self, connector: Connector) -> dict[str, str]:
        """Config field name -> decrypted value, for every resource the connector references.

        Values are stripped of surrounding whitespace: these are tokens/passwords used as HTTP
        credentials, where a trailing newline from a file-sourced resource would break auth.
        """
        secrets: dict[str, str] = {}
        for field_name, (resource_id, _type) in connector_resource_refs(connector.spec).items():
            resource = await self._repo.get_resource(resource_id)
            if resource is None:
                raise ConfigurationError(
                    f"Resource {resource_id!r} referenced by connector {connector.id!r} "
                    "does not exist"
                )
            secrets[field_name] = self._cipher.decrypt(resource.ciphertext).decode("utf-8").strip()
        return secrets
