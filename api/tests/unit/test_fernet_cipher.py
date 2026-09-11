"""Unit tests for infrastructure/crypto/fernet_cipher.py (resource encryption at rest)."""

from __future__ import annotations

import hashlib

import pytest
from cryptography.fernet import Fernet

from capataz_api.domain.exceptions import ConfigurationError
from capataz_api.infrastructure.crypto import FernetResourceCipher, parse_master_keys

# Shared with runner/tests/test_crypto.py: both sides must decrypt this exact token, so the API's
# encryption and the runner's decryption can never silently drift apart. Test-only key.
SHARED_VECTOR_KEY = "8tqAJmPr27f8r7U4yZZMgMC8TR44rrc-Zdrdru4ONDo="
SHARED_VECTOR_TOKEN = (
    "gAAAAABqo8GsAWr4hLnBO4OYkUH3NMRIRB1oVSS-81GGN_jUu8FqHZWKFpXbvyxXWbH79Ei0T2bFBDsHcWX3H6ZQ"
    "4h0XOF4N0NL3cTS5lII1VEvFJsI8-jz60vjiBc2ZQM7pVKsr564KgTusqdPuRcDF4r8VF08XjQ=="
)
SHARED_VECTOR_PLAINTEXT = b"capataz-shared-test-vector\n-----BEGIN KEY-----\nabc\n"


def test_decrypts_the_vector_shared_with_the_runner() -> None:
    cipher = FernetResourceCipher([SHARED_VECTOR_KEY])
    assert cipher.decrypt(SHARED_VECTOR_TOKEN.encode()) == SHARED_VECTOR_PLAINTEXT


def test_encrypt_decrypt_round_trip_never_stores_plaintext() -> None:
    cipher = FernetResourceCipher([Fernet.generate_key().decode()])
    ciphertext = cipher.encrypt(b"super-secret-token")
    assert b"super-secret-token" not in ciphertext
    assert cipher.decrypt(ciphertext) == b"super-secret-token"


def test_rotation_new_primary_key_still_decrypts_data_written_with_the_old_one() -> None:
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    written_before_rotation = FernetResourceCipher([old_key]).encrypt(b"payload")
    rotated = FernetResourceCipher([new_key, old_key])
    assert rotated.decrypt(written_before_rotation) == b"payload"
    # New writes use the new primary key only, so they no longer need the old one.
    assert FernetResourceCipher([new_key]).decrypt(rotated.encrypt(b"fresh")) == b"fresh"


def test_undecryptable_ciphertext_is_a_configuration_error_without_details() -> None:
    cipher = FernetResourceCipher([Fernet.generate_key().decode()])
    with pytest.raises(ConfigurationError, match="could not be decrypted"):
        cipher.decrypt(SHARED_VECTOR_TOKEN.encode())


def test_invalid_master_key_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="invalid Fernet key"):
        FernetResourceCipher(["not-a-fernet-key"])


def test_empty_key_list_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="no keys"):
        FernetResourceCipher([])


def test_fingerprint_is_stable_keyed_and_content_sensitive() -> None:
    cipher = FernetResourceCipher([SHARED_VECTOR_KEY])
    first = cipher.fingerprint(b"token-a")
    assert first == cipher.fingerprint(b"token-a")
    assert first != cipher.fingerprint(b"token-b")
    # Keyed: not guessable from the content alone.
    assert first != hashlib.sha256(b"token-a").hexdigest()
    other_key = FernetResourceCipher([Fernet.generate_key().decode()])
    assert first != other_key.fingerprint(b"token-a")


def test_parse_master_keys_ignores_blank_lines_and_comments() -> None:
    raw = f"# rotated 2026-09\n\n  {SHARED_VECTOR_KEY}  \n# old\nsecond-key\n"
    assert parse_master_keys(raw) == (SHARED_VECTOR_KEY, "second-key")


def test_parse_master_keys_rejects_a_secret_with_no_keys() -> None:
    with pytest.raises(ConfigurationError, match="no keys"):
        parse_master_keys("# only a comment\n\n")


def test_from_secret_builds_a_working_cipher() -> None:
    cipher = FernetResourceCipher.from_secret(f"{SHARED_VECTOR_KEY}\n")
    assert cipher.decrypt(SHARED_VECTOR_TOKEN.encode()) == SHARED_VECTOR_PLAINTEXT
