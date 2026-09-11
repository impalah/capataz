"""Unit tests for the resource-related settings (inline content opt-in, resources_dir)."""

from __future__ import annotations

from pathlib import Path

import pytest

from capataz_api.core.settings import Settings


@pytest.mark.parametrize(
    ("env", "allow", "permitted"),
    [
        ("development", False, True),
        ("development", True, True),
        ("production", False, False),
        ("production", True, True),
    ],
)
def test_inline_resources_are_refused_in_production_unless_explicitly_allowed(
    env: str, allow: bool, permitted: bool
) -> None:
    settings = Settings(auth_mode="cognito", env=env, allow_inline_resources=allow)
    assert settings.inline_resources_permitted is permitted


def test_resources_dir_defaults_to_the_mounted_resources_directory() -> None:
    assert Settings(auth_mode="cognito").resources_dir == Path("/run/capataz-resources")
