from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from capataz_runner.config import Settings
from capataz_runner.crypto import ResourceDecryptionError, ResourceDecryptor, parse_master_keys

# Shared with api/tests/unit/test_fernet_cipher.py: the API encrypts, the runner decrypts, and
# both suites must decrypt this exact token so the two implementations can't drift apart.
SHARED_VECTOR_KEY = "8tqAJmPr27f8r7U4yZZMgMC8TR44rrc-Zdrdru4ONDo="
SHARED_VECTOR_TOKEN = (
    "gAAAAABqo8GsAWr4hLnBO4OYkUH3NMRIRB1oVSS-81GGN_jUu8FqHZWKFpXbvyxXWbH79Ei0T2bFBDsHcWX3H6ZQ"
    "4h0XOF4N0NL3cTS5lII1VEvFJsI8-jz60vjiBc2ZQM7pVKsr564KgTusqdPuRcDF4r8VF08XjQ=="
)
SHARED_VECTOR_PLAINTEXT = b"capataz-shared-test-vector\n-----BEGIN KEY-----\nabc\n"


def test_decrypts_the_vector_shared_with_the_api() -> None:
    decryptor = ResourceDecryptor([SHARED_VECTOR_KEY])
    assert decryptor.decrypt(SHARED_VECTOR_TOKEN.encode()) == SHARED_VECTOR_PLAINTEXT


def test_decrypts_with_any_configured_key_after_rotation() -> None:
    decryptor = ResourceDecryptor([Fernet.generate_key().decode(), SHARED_VECTOR_KEY])
    assert decryptor.decrypt(SHARED_VECTOR_TOKEN.encode()) == SHARED_VECTOR_PLAINTEXT


def test_wrong_key_raises_without_leaking_details() -> None:
    decryptor = ResourceDecryptor([Fernet.generate_key().decode()])
    with pytest.raises(ResourceDecryptionError, match="could not be decrypted"):
        decryptor.decrypt(SHARED_VECTOR_TOKEN.encode())


def test_invalid_or_missing_keys_are_rejected() -> None:
    with pytest.raises(ResourceDecryptionError, match="invalid Fernet key"):
        ResourceDecryptor(["nope"])
    with pytest.raises(ResourceDecryptionError, match="no keys"):
        ResourceDecryptor([])


def test_parse_master_keys_skips_comments_and_blank_lines() -> None:
    assert parse_master_keys(f"# primary\n{SHARED_VECTOR_KEY}\n\nold-key\n") == (
        SHARED_VECTOR_KEY,
        "old-key",
    )
    with pytest.raises(ResourceDecryptionError, match="no keys"):
        parse_master_keys("\n# nothing\n")


def test_settings_read_master_keys_from_the_docker_secret() -> None:
    assert Settings().resources_master_keys == (SHARED_VECTOR_KEY,)
