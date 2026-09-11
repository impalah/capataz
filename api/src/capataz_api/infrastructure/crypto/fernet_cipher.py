"""Fernet encryption of resources at rest (docs/adr/008-connectors-and-resources).

The ``resources_master_key`` Docker secret holds one Fernet key per line: the first encrypts,
all of them decrypt (MultiFernet), which is what makes key rotation possible. The runner has a
decrypt-only counterpart (runner/src/capataz_runner/crypto.py); both test suites decrypt the same
shared vector so the two can't drift apart.
"""

import base64
import hashlib
import hmac
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from capataz_api.domain.exceptions import ConfigurationError

_FINGERPRINT_CONTEXT = b"capataz-resource-fingerprint-v1"


def parse_master_keys(raw: str) -> tuple[str, ...]:
    keys = tuple(
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    if not keys:
        raise ConfigurationError("resources_master_key contains no keys")
    return keys


class FernetResourceCipher:
    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise ConfigurationError("resources_master_key contains no keys")
        try:
            fernets = [Fernet(key.encode("ascii")) for key in keys]
        except ValueError:
            raise ConfigurationError(
                "resources_master_key contains an invalid Fernet key"
            ) from None
        self._fernet = MultiFernet(fernets)
        # A keyed fingerprint (not a bare SHA-256) so a stored fingerprint can't be used to
        # confirm a guess of a low-entropy secret such as a short token or password.
        primary = base64.urlsafe_b64decode(keys[0])
        self._fingerprint_key = hmac.new(primary, _FINGERPRINT_CONTEXT, hashlib.sha256).digest()

    @classmethod
    def from_secret(cls, raw: str) -> FernetResourceCipher:
        return cls(parse_master_keys(raw))

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken:
            raise ConfigurationError(
                "Resource could not be decrypted with the configured master key(s)"
            ) from None

    def fingerprint(self, plaintext: bytes) -> str:
        return hmac.new(self._fingerprint_key, plaintext, hashlib.sha256).hexdigest()
