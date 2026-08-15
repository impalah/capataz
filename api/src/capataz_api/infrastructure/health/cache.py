import asyncio
import json
import time
from typing import Any

from redis.asyncio import Redis


class RedisStatusCache:
    def __init__(self, client: Redis) -> None:
        self.client = client

    async def get(self, service_id: str) -> dict[str, Any] | None:
        raw = await self.client.get(f"capataz:status:{service_id}")
        return json.loads(raw) if raw else None

    async def set(self, service_id: str, value: dict[str, Any], ttl: int) -> None:
        await self.client.set(f"capataz:status:{service_id}", json.dumps(value), ex=ttl)


class InMemoryStatusCache:
    """Process-local StatusCache used where Redis isn't available (e.g. local dev).

    Mirrors RedisStatusCache's `ttl` semantics with a real expiry, and guards the shared
    dict with an asyncio.Lock since multiple request-handling coroutines can call
    get()/set() concurrently on the same event loop.
    """

    def __init__(self) -> None:
        self.values: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, service_id: str) -> dict[str, Any] | None:
        async with self._lock:
            entry = self.values.get(service_id)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                del self.values[service_id]
                return None
            return value

    async def set(self, service_id: str, value: dict[str, Any], ttl: int) -> None:
        async with self._lock:
            self.values[service_id] = (time.monotonic() + ttl, value)
