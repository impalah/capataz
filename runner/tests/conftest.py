from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def secrets_dir(tmp_path: Path) -> Path:
    values = {
        "database_url": "postgresql+asyncpg://capataz:postgres-super-secret@postgres:5432/capataz",
        "redis_url": "redis://:redis-super-secret@redis:6379/0",
        "portainer_token": "portainer-super-secret",
        "runner_ssh_private_key": "not-a-real-private-key",
        "runner_known_hosts": "node-ai-01 ssh-ed25519 AAAA",
        "ansible_vault_password": "vault-super-secret",
    }
    for name, value in values.items():
        (tmp_path / name).write_text(value, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def capataz_test_environment(secrets_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPATAZ_SECRETS_DIR", str(secrets_dir))
    monkeypatch.setenv("CAPATAZ_PROJECT_ROOT", "/home/user/workspace/capataz/runner")
    monkeypatch.setenv("CAPATAZ_PORTAINER_URL", "https://portainer.home.arpa")
