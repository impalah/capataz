"""Resource/connector repository round-trips against a real Postgres (bytea + JSONB)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from capataz_api.domain.entities import Connector, Resource
from capataz_api.domain.specs import CONNECTOR_SPEC_ADAPTER, SshConnector
from capataz_api.domain.value_objects import ResourceType
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


@pytest.mark.asyncio
async def test_resource_bytes_and_connector_config_round_trip_on_postgres(
    pg_engine: AsyncEngine,
) -> None:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    ciphertext = bytes(range(256))  # every byte value survives bytea storage
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_resource(
            Resource(
                id="ssh_mole_key",
                type=ResourceType.SSH_PRIVATE_KEY,
                ciphertext=ciphertext,
                fingerprint="a" * 64,
                size=256,
                source={"env": "SSH_MOLE_KEY_B64"},
            )
        )
        await repo.upsert_connector(
            Connector(
                spec=CONNECTOR_SPEC_ADAPTER.validate_python(
                    {
                        "id": "ssh_mole",
                        "type": "ssh",
                        "config": {
                            "host": "mole.404labo.net",
                            "user": "capataz",
                            "private_key": "ssh_mole_key",
                            "known_hosts": "homelab_known_hosts",
                        },
                    }
                )
            )
        )
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        resource = await repo.get_resource("ssh_mole_key")
        connector = await repo.get_connector("ssh_mole")
    assert resource is not None and resource.ciphertext == ciphertext
    assert connector is not None and isinstance(connector.spec, SshConnector)
    assert connector.spec.config.private_key == "ssh_mole_key"
    assert connector.spec.config.port == 22
