"""SSRF defenses for every URL or host Capataz calls out to (docs/06-security).

`CAPATAZ_HEALTH_ALLOWED_HOST_SUFFIXES` is the global ceiling: connector URLs, health URLs and SSH
hosts must all fall inside it, and an http connector's own allow-list can only narrow it.
"""

import ipaddress
from urllib.parse import urlparse

from capataz_api.domain.exceptions import ValidationError


def _dotted(suffix: str) -> str:
    return "." + suffix.lower().lstrip(".")


def suffix_within(suffix: str, ceiling: tuple[str, ...]) -> bool:
    """True when `suffix` is one of the ceiling suffixes or a subdomain suffix of one."""
    candidate = _dotted(suffix)
    return any(candidate.endswith(_dotted(allowed)) for allowed in ceiling)


def narrow_suffixes(requested: tuple[str, ...], ceiling: tuple[str, ...]) -> tuple[str, ...]:
    """A connector's allow-list intersected with the ceiling; empty request = the ceiling itself.

    Anything outside the ceiling is dropped (not trusted), so a narrowed list that ends up empty
    fails closed in validate_outbound_url.
    """
    if not requested:
        return ceiling
    return tuple(suffix for suffix in requested if suffix_within(suffix, ceiling))


def validate_outbound_url(
    url: str, allowed_suffixes: tuple[str, ...], label: str = "Health"
) -> None:
    """Validate scheme/host before any request; see docs/06-security.en.md for the residual
    DNS-rebinding risk (this checks the hostname string, not the IP httpx actually resolves
    and connects to; accepted given the closed homelab trust model where suffix-allow-listed
    DNS is operator-owned — CR-038 in docs/code-review-2026-08.md)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError(f"{label} URL must use http or https and include a hostname")
    host = parsed.hostname.lower()
    # Empty allow-list must fail closed (reject everything), never be treated as "no restriction".
    if not allowed_suffixes:
        raise ValidationError(f"No {label.lower()} host suffixes are allow-listed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
            raise ValidationError(f"{label} hostname is not allow-listed") from None
        if not any(host.endswith(suffix) for suffix in allowed_suffixes):
            raise ValidationError(f"{label} hostname is not allow-listed") from None
    else:
        if address.is_loopback or address.is_link_local or address.is_private:
            raise ValidationError(f"Private or metadata IP {label.lower()} targets are not allowed")
        if not any(host.endswith(suffix.lstrip(".")) for suffix in allowed_suffixes):
            raise ValidationError(f"IP {label.lower()} targets are not allowed")


def validate_outbound_host(host: str, allowed_suffixes: tuple[str, ...], label: str) -> None:
    """Same hostname/IP rules as validate_outbound_url, for a bare host (e.g. an SSH target)."""
    validate_outbound_url(f"https://{host}/", allowed_suffixes, label)
