import ipaddress
from urllib.parse import urlparse

import httpx

from capataz_api.domain.exceptions import ValidationError


def validate_health_url(url: str, allowed_suffixes: tuple[str, ...]) -> None:
    """Validate scheme/host before probing; see docs/06-security.en.md for the residual
    DNS-rebinding risk (this checks the hostname string, not the IP httpx actually
    resolves and connects to; accepted given the closed homelab trust model where
    suffix-allow-listed DNS is operator-owned — CR-038 in docs/code-review-2026-08.md)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("Health URL must use http or https and include a hostname")
    host = parsed.hostname.lower()
    # Empty allow-list must fail closed (reject everything), never be treated as "no restriction".
    if not allowed_suffixes:
        raise ValidationError("No health host suffixes are allow-listed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
            raise ValidationError("Health hostname is not allow-listed") from None
        if not any(host.endswith(suffix) for suffix in allowed_suffixes):
            raise ValidationError("Health hostname is not allow-listed") from None
    else:
        if address.is_loopback or address.is_link_local or address.is_private:
            raise ValidationError("Private or metadata IP health targets are not allowed")
        if not any(host.endswith(suffix.lstrip(".")) for suffix in allowed_suffixes):
            raise ValidationError("IP health targets are not allowed")


class HttpHealthProber:
    def __init__(self, allowed_suffixes: tuple[str, ...], default_timeout: float = 5) -> None:
        self.allowed_suffixes, self.default_timeout = allowed_suffixes, default_timeout

    async def probe(self, config: dict[str, object]) -> bool:
        url = str(config.get("url", ""))
        validate_health_url(url, self.allowed_suffixes)
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=float(config.get("timeout_seconds", self.default_timeout)),
            ) as client:
                response = await client.get(url)
            return response.status_code == int(str(config.get("expected_status", 200)))
        except httpx.HTTPError:
            return False
