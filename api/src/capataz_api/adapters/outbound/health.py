import httpx

from capataz_api.application.policies import validate_outbound_url


def validate_health_url(url: str, allowed_suffixes: tuple[str, ...]) -> None:
    validate_outbound_url(url, allowed_suffixes, "Health")


class HttpHealthProber:
    def __init__(
        self, allowed_suffixes: tuple[str, ...], default_timeout: float = 5, verify: bool = True
    ) -> None:
        self.allowed_suffixes, self.default_timeout = allowed_suffixes, default_timeout
        self.verify = verify

    async def probe(self, config: dict[str, object]) -> bool:
        url = str(config.get("url", ""))
        validate_health_url(url, self.allowed_suffixes)
        method = str(config.get("method", "GET")).upper()
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=float(str(config.get("timeout_seconds", self.default_timeout))),
                verify=self.verify,
            ) as client:
                response = await client.request(method, url)
            return response.status_code == int(str(config.get("expected_status", 200)))
        except httpx.HTTPError:
            return False
