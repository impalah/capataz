"""Shared fixtures for tests/integration/: a real Postgres container, not SQLite.

`test_repositories.py` used to run against `sqlite+aiosqlite`, which never enforces foreign-key
constraints unless `PRAGMA foreign_keys=ON` is explicitly set (this project never did). That let a
real bug (a service/action delete failing against Postgres due to a FK violation) pass its
supposedly-covering unit test unnoticed: SQLite silently allowed the delete SQLite would have
rejected. These tests now run against a real Postgres.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from capataz_api.infrastructure.database.models import Base


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip(
            "Testcontainers integration requires a Docker daemon; unavailable in this sandbox"
        )
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture
async def pg_engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    """A real Postgres engine with the schema created and every table emptied beforehand.

    One container for the whole test session (slow to start, cheap to reuse); each test gets a
    clean slate via a plain DELETE per table in reverse dependency order — cheaper than tearing
    the container down and avoids needing to track/reset any sequences (every PK here is a
    Python-side UUID default, not a DB SERIAL).
    """
    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    yield engine
    await engine.dispose()
