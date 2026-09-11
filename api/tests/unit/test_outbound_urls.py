"""application/policies/outbound_urls.py: the shared SSRF ceiling for every outbound target."""

from __future__ import annotations

import pytest

from capataz_api.application.policies import (
    narrow_suffixes,
    suffix_within,
    validate_outbound_host,
    validate_outbound_url,
)
from capataz_api.domain.exceptions import ValidationError

CEILING = (".home.arpa",)


@pytest.mark.parametrize(
    ("suffix", "inside"),
    [
        (".home.arpa", True),
        ("home.arpa", True),
        (".lab.home.arpa", True),
        (".evilhome.arpa", False),
        (".example.com", False),
    ],
)
def test_suffix_within_matches_whole_labels_only(suffix: str, inside: bool) -> None:
    assert suffix_within(suffix, CEILING) is inside


def test_narrow_suffixes_inherits_filters_and_can_fail_closed() -> None:
    assert narrow_suffixes((), CEILING) == CEILING
    assert narrow_suffixes((".lab.home.arpa", ".example.com"), CEILING) == (".lab.home.arpa",)
    assert narrow_suffixes((".example.com",), CEILING) == ()
    with pytest.raises(ValidationError, match="No health host suffixes"):
        validate_outbound_url("https://a.home.arpa", narrow_suffixes((".example.com",), CEILING))


def test_messages_name_what_was_being_validated() -> None:
    with pytest.raises(ValidationError, match="Connector hostname is not allow-listed"):
        validate_outbound_url("https://portainer.evil.example", CEILING, "Connector")
    with pytest.raises(ValidationError, match="Connector URL must use http or https"):
        validate_outbound_url("ftp://portainer.home.arpa", CEILING, "Connector")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "169.254.169.254", "mole.local"])
def test_validate_outbound_host_applies_the_same_rules_to_bare_hosts(host: str) -> None:
    validate_outbound_host("mole.home.arpa", CEILING, "SSH")
    with pytest.raises(ValidationError):
        validate_outbound_host(host, CEILING, "SSH")
