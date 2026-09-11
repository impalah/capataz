"""Loads catalog resource content from its declared source, confined to safe locations.

File sources are resolved against CAPATAZ_RESOURCES_DIR and must stay inside it after following
symlinks; without that confinement an admin could import e.g. /run/secrets/database_url as a
resource and exfiltrate it through a connector (docs/06-security).
"""

import base64
import os
from collections.abc import Mapping
from pathlib import Path

from capataz_api.domain.exceptions import ValidationError
from capataz_api.domain.specs import (
    MAX_RESOURCE_BYTES,
    EnvSource,
    FileSource,
    InlineSource,
    ResourceSource,
)


class FileSystemResourceSourceLoader:
    def __init__(self, resources_dir: Path, environ: Mapping[str, str] | None = None) -> None:
        self._resources_dir = resources_dir
        self._environ = environ if environ is not None else os.environ

    def load(self, source: ResourceSource) -> bytes:
        if isinstance(source, FileSource):
            return self._load_file(source.file)
        if isinstance(source, EnvSource):
            return self._load_env(source)
        assert isinstance(source, InlineSource)
        return self._checked(base64.b64decode(source.base64))

    def _load_file(self, relative: str) -> bytes:
        base = self._resources_dir.resolve()
        if not base.is_dir():
            raise ValidationError(f"CAPATAZ_RESOURCES_DIR {str(base)!r} is not a directory")
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base):
            raise ValidationError(f"resource file {relative!r} escapes CAPATAZ_RESOURCES_DIR")
        if not candidate.is_file():
            raise ValidationError(f"resource file {relative!r} does not exist")
        if candidate.stat().st_size > MAX_RESOURCE_BYTES:
            raise ValidationError(f"resource file {relative!r} exceeds {MAX_RESOURCE_BYTES} bytes")
        return candidate.read_bytes()

    def _load_env(self, source: EnvSource) -> bytes:
        value = self._environ.get(source.env)
        if value is None:
            raise ValidationError(f"environment variable {source.env} is not set")
        if source.encoding == "plain":
            return self._checked(value.encode("utf-8"))
        try:
            decoded = base64.b64decode("".join(value.split()), validate=True)
        except ValueError:
            raise ValidationError(
                f"environment variable {source.env} is not valid base64"
            ) from None
        return self._checked(decoded)

    @staticmethod
    def _checked(content: bytes) -> bytes:
        if not content:
            raise ValidationError("resource content is empty")
        if len(content) > MAX_RESOURCE_BYTES:
            raise ValidationError(f"resource content exceeds {MAX_RESOURCE_BYTES} bytes")
        return content
