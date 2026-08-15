#!/usr/bin/env python3
"""Small operational client for Capataz's authenticated catalog endpoints."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def api_url(path: str) -> str:
    base = os.environ.get("CAPATAZ_API_URL", "http://localhost:8000/api/v1").rstrip("/")
    return f"{base}{path}"


def headers(content_type: bool = False) -> dict[str, str]:
    result = {"Accept": "application/yaml" if not content_type else "application/json"}
    authorization = os.environ.get("CAPATAZ_API_AUTHORIZATION", "").strip()
    if authorization:
        result["Authorization"] = authorization
    else:
        # Defaults are only for the documented local dev_mock workflow.
        result["X-Dev-User"] = "local-admin"
        result["X-Dev-Groups"] = "capataz-admin"
    if content_type:
        result["Content-Type"] = "application/json"
    return result


def request(method: str, path: str, body: bytes | None = None) -> bytes:
    try:
        message = Request(api_url(path), data=body, headers=headers(body is not None), method=method)
        with urlopen(message, timeout=15) as response:
            return response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API respondió {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"No se pudo conectar con la API: {error.reason}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente operativo del catálogo Capataz")
    subcommands = parser.add_subparsers(dest="command", required=True)
    import_command = subcommands.add_parser("import", help="importa un YAML por API")
    import_command.add_argument("catalog", type=Path)
    subcommands.add_parser("export", help="exporta el catálogo YAML por API")
    args = parser.parse_args()

    if args.command == "import":
        payload = json.dumps({"yaml": args.catalog.read_text(encoding="utf-8"), "dry_run": False}).encode()
        sys.stdout.write(request("POST", "/catalog/import", payload).decode("utf-8") + "\n")
    else:
        sys.stdout.write(request("GET", "/catalog/export").decode("utf-8"))


if __name__ == "__main__":
    main()
