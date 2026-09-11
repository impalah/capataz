"""Resource specs: metadata and load source of an encrypted file/secret stored by Capataz.

The spec never carries the plaintext itself except for ``InlineSource``, which exists only for
development/tests and is rejected in production unless explicitly allowed (see docs/06-security).
"""

import base64

from pydantic import Field, field_validator

from capataz_api.domain.specs.common import ReferenceId, SpecModel
from capataz_api.domain.value_objects import ResourceType

MAX_RESOURCE_BYTES = 64 * 1024


class FileSource(SpecModel):
    # Relative to CAPATAZ_RESOURCES_DIR. Every segment must start with an alphanumeric character,
    # which rules out absolute paths and "."/".." segments here; symlink escapes are checked at
    # load time against the resolved real path.
    file: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$", max_length=255
    )


class EnvSource(SpecModel):
    env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$", max_length=128)
    encoding: str = Field(default="plain", pattern=r"^(plain|base64)$")


class InlineSource(SpecModel):
    base64: str = Field(min_length=1)

    @field_validator("base64")
    @classmethod
    def must_be_valid_base64(cls, value: str) -> str:
        compact = "".join(value.split())
        try:
            decoded = base64.b64decode(compact, validate=True)
        except ValueError:
            raise ValueError("inline resource content is not valid base64") from None
        if len(decoded) > MAX_RESOURCE_BYTES:
            raise ValueError(f"inline resource content exceeds {MAX_RESOURCE_BYTES} bytes")
        return compact


ResourceSource = FileSource | EnvSource | InlineSource


class ResourceSpec(SpecModel):
    id: ReferenceId
    type: ResourceType
    description: str | None = Field(default=None, max_length=500)
    source: ResourceSource | None = None
