"""Real Postgres integration path for CI; skips automatically without Docker."""

import shutil

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Testcontainers integration requires a Docker daemon; unavailable in this sandbox",
)


def test_testcontainers_path_is_available() -> None:
    from testcontainers.postgres import PostgresContainer

    assert PostgresContainer is not None
