"""Decrypt-only counterpart of the API's FernetResourceCipher.

The API (capataz_api.infrastructure.crypto.fernet_cipher) encrypts resources at rest with the
``resources_master_key`` Docker secret — one Fernet key per line, the first one encrypts and all
of them decrypt. The runner only ever decrypts, right before an execution needs the value.
"""

from __future__ import annotations

from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class ResourceDecryptionError(RuntimeError):
    """A resource could not be decrypted, or the master key secret is unusable."""


def parse_master_keys(raw: str) -> tuple[str, ...]:
    keys = tuple(
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    if not keys:
        raise ResourceDecryptionError("resources_master_key contains no keys")
    return keys


class ResourceDecryptor:
    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise ResourceDecryptionError("resources_master_key contains no keys")
        try:
            self._fernet = MultiFernet([Fernet(key.encode("ascii")) for key in keys])
        except ValueError:
            raise ResourceDecryptionError(
                "resources_master_key contains an invalid Fernet key"
            ) from None

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken:
            raise ResourceDecryptionError(
                "Resource could not be decrypted with the configured master key(s)"
            ) from None
