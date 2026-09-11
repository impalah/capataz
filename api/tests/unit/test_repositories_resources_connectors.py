"""SQLite smoke coverage for the resource/connector methods of repositories.py.

Postgres-specific behaviour (bytea, JSONB) is covered in
tests/integration/test_resource_connector_repositories.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from capataz_api.domain.entities import Connector, Resource
from capataz_api.domain.exceptions import ConflictError
from capataz_api.domain.specs import CONNECTOR_SPEC_ADAPTER, PortainerConnector
from capataz_api.domain.value_objects import ConnectorType, ResourceType
from capataz_api.infrastructure.database.models import Base
from capataz_api.infrastructure.database.repositories import SqlAlchemyRepository


async def _empty_engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


def _portainer(url: str = "https://portainer.404labo.net") -> Connector:
    return Connector(
        spec=CONNECTOR_SPEC_ADAPTER.validate_python(
            {
                "id": "portainer_main",
                "type": "portainer",
                "description": "Main Portainer",
                "config": {"url": url, "token": "portainer_token"},
            }
        )
    )


@pytest.mark.asyncio
async def test_resource_round_trip_and_version_bump_on_update(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        created = await repo.upsert_resource(
            Resource(
                id="ssh_mole_key",
                type=ResourceType.SSH_PRIVATE_KEY,
                ciphertext=b"gAAAAA-ciphertext",
                fingerprint="f" * 64,
                size=411,
                source={"file": "ssh_mole_key"},
            )
        )
        assert created.version == 1
        created.ciphertext, created.fingerprint = b"gAAAAA-rotated", "e" * 64
        updated = await repo.upsert_resource(created)
        await session.commit()

    assert updated.version == 2
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        loaded = await repo.get_resource("ssh_mole_key")
        listed = await repo.list_resources()
    assert loaded is not None
    assert loaded.ciphertext == b"gAAAAA-rotated"
    assert loaded.type is ResourceType.SSH_PRIVATE_KEY
    assert loaded.source == {"file": "ssh_mole_key"}
    assert [resource.id for resource in listed] == ["ssh_mole_key"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_connector_round_trip_rebuilds_the_typed_spec_without_redacting_refs(
    tmp_path: Path,
) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await SqlAlchemyRepository(session).upsert_connector(_portainer())
        await session.commit()

    async with factory() as session:
        loaded = await SqlAlchemyRepository(session).get_connector("portainer_main")
    assert loaded is not None
    assert isinstance(loaded.spec, PortainerConnector)
    assert loaded.type is ConnectorType.PORTAINER
    assert loaded.spec.description == "Main Portainer"
    # sanitize() would have turned this into "[REDACTED]" (its key regex matches "token").
    assert loaded.spec.config.token == "portainer_token"
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_connector_raises_conflict_on_stale_version(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await SqlAlchemyRepository(session).upsert_connector(_portainer())
        await session.commit()

    async with factory() as first_session, factory() as second_session:
        first, second = SqlAlchemyRepository(first_session), SqlAlchemyRepository(second_session)
        first_copy = await first.get_connector("portainer_main")
        second_copy = await second.get_connector("portainer_main")
        assert first_copy is not None and second_copy is not None
        await first.upsert_connector(first_copy, enforce_version=True)
        await first_session.commit()
        with pytest.raises(ConflictError):
            await second.upsert_connector(second_copy, enforce_version=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_resource_and_connector_report_missing_rows(tmp_path: Path) -> None:
    engine = await _empty_engine(tmp_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = SqlAlchemyRepository(session)
        await repo.upsert_connector(_portainer())
        await repo.upsert_resource(
            Resource(
                id="portainer_token",
                type=ResourceType.SECRET,
                ciphertext=b"x",
                fingerprint="0" * 64,
                size=1,
            )
        )
        assert await repo.delete_connector("portainer_main") is True
        assert await repo.delete_connector("portainer_main") is False
        assert await repo.delete_resource("portainer_token") is True
        assert await repo.delete_resource("portainer_token") is False
        assert await repo.list_connectors() == []
    await engine.dispose()
