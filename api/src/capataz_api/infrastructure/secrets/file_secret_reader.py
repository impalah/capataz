from pathlib import Path

from loguru import logger

from capataz_api.domain.exceptions import ConfigurationError

# Group/other read/write/execute bits: a secret file mounted more permissively than owner-only
# is a hardening concern worth flagging, even though the container's own filesystem boundary is
# the primary control (CR-039 in docs/code-review-2026-08.md).
_OVERLY_PERMISSIVE_MODE_MASK = 0o077


class FileSecretReader:
    def __init__(self, directory: Path = Path("/run/secrets")) -> None:
        self.directory = directory

    def read(self, name: str, required: bool = True) -> str | None:
        path = self.directory / name
        try:
            self._warn_if_overly_permissive(path)
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            if required:
                raise ConfigurationError(f"Required secret {name!r} is not mounted") from None
            return None
        if required and not value:
            raise ConfigurationError(f"Required secret {name!r} is empty")
        return value or None

    @staticmethod
    def _warn_if_overly_permissive(path: Path) -> None:
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return
        if mode & _OVERLY_PERMISSIVE_MODE_MASK:
            logger.warning(
                "Secret file {} is readable/writable by group or other (mode {:o}); "
                "expected owner-only (e.g. chmod 600)",
                path,
                mode & 0o777,
            )


def read_secret(name: str, required: bool = True) -> str | None:
    return FileSecretReader().read(name, required)
