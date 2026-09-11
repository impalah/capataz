from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

SERVICE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
REFERENCE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,127}$"

ReferenceId = Annotated[str, StringConstraints(pattern=REFERENCE_ID_PATTERN)]


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
