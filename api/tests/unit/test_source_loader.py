"""infrastructure/resources/source_loader.py: resource content confined to safe sources."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from capataz_api.domain.exceptions import ValidationError
from capataz_api.domain.specs import MAX_RESOURCE_BYTES, EnvSource, FileSource, InlineSource
from capataz_api.infrastructure.resources import FileSystemResourceSourceLoader


def loader(resources_dir: Path, **environ: str) -> FileSystemResourceSourceLoader:
    return FileSystemResourceSourceLoader(resources_dir, environ=environ)


def test_loads_a_file_inside_the_resources_dir(tmp_path: Path) -> None:
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "mole.pem").write_bytes(b"-----BEGIN KEY-----\n")
    assert loader(tmp_path).load(FileSource(file="keys/mole.pem")) == b"-----BEGIN KEY-----\n"


def test_rejects_a_symlink_that_escapes_the_resources_dir(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    (tmp_path / "database_url").write_text("postgresql://user:pass@db/capataz")
    (resources / "innocent").symlink_to(tmp_path / "database_url")
    with pytest.raises(ValidationError, match="escapes CAPATAZ_RESOURCES_DIR"):
        loader(resources).load(FileSource(file="innocent"))


def test_rejects_missing_files_oversized_files_and_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        loader(tmp_path).load(FileSource(file="nope"))
    (tmp_path / "big").write_bytes(b"x" * (MAX_RESOURCE_BYTES + 1))
    with pytest.raises(ValidationError, match="exceeds"):
        loader(tmp_path).load(FileSource(file="big"))
    with pytest.raises(ValidationError, match="is not a directory"):
        loader(tmp_path / "missing-dir").load(FileSource(file="anything"))


def test_env_sources_support_plain_and_base64(tmp_path: Path) -> None:
    source_loader = loader(tmp_path, PLAIN="token", B64=base64.b64encode(b"\x00binary").decode())
    assert source_loader.load(EnvSource(env="PLAIN")) == b"token"
    assert source_loader.load(EnvSource(env="B64", encoding="base64")) == b"\x00binary"


def test_env_sources_report_missing_invalid_and_empty_values(tmp_path: Path) -> None:
    source_loader = loader(tmp_path, BAD="***", EMPTY="")
    with pytest.raises(ValidationError, match="is not set"):
        source_loader.load(EnvSource(env="MISSING"))
    with pytest.raises(ValidationError, match="not valid base64"):
        source_loader.load(EnvSource(env="BAD", encoding="base64"))
    with pytest.raises(ValidationError, match="empty"):
        source_loader.load(EnvSource(env="EMPTY"))


def test_inline_sources_are_decoded(tmp_path: Path) -> None:
    encoded = base64.b64encode(b"inline").decode()
    assert loader(tmp_path).load(InlineSource(base64=encoded)) == b"inline"
