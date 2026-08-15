"""Unit tests for infrastructure/health/cache.py: InMemoryStatusCache and RedisStatusCache."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from capataz_api.infrastructure.health.cache import InMemoryStatusCache, RedisStatusCache


@pytest.mark.asyncio
async def test_in_memory_cache_get_returns_none_when_missing() -> None:
    cache = InMemoryStatusCache()
    assert await cache.get("svc") is None


@pytest.mark.asyncio
async def test_in_memory_cache_set_then_get_round_trips() -> None:
    cache = InMemoryStatusCache()
    await cache.set("svc", {"status": "healthy"}, ttl=30)
    assert await cache.get("svc") == {"status": "healthy"}


@pytest.mark.asyncio
async def test_in_memory_cache_expires_entries_past_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = InMemoryStatusCache()
    fake_now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    await cache.set("svc", {"status": "healthy"}, ttl=10)
    fake_now[0] = 1011.0  # past expiry
    assert await cache.get("svc") is None
    assert "svc" not in cache.values  # expired entry is evicted, not just hidden


@pytest.mark.asyncio
async def test_in_memory_cache_serialises_concurrent_access_via_lock() -> None:
    cache = InMemoryStatusCache()
    results = await asyncio.gather(
        *(cache.set(f"svc-{i}", {"status": "healthy"}, ttl=30) for i in range(20))
    )
    assert results == [None] * 20
    for i in range(20):
        assert await cache.get(f"svc-{i}") == {"status": "healthy"}


@pytest.mark.asyncio
async def test_redis_cache_get_deserialises_json_when_present() -> None:
    client = AsyncMock()
    client.get.return_value = json.dumps({"status": "down"})
    cache = RedisStatusCache(client)
    result = await cache.get("svc")
    assert result == {"status": "down"}
    client.get.assert_awaited_once_with("capataz:status:svc")


@pytest.mark.asyncio
async def test_redis_cache_get_returns_none_when_key_missing() -> None:
    client = AsyncMock()
    client.get.return_value = None
    cache = RedisStatusCache(client)
    assert await cache.get("svc") is None


@pytest.mark.asyncio
async def test_redis_cache_set_serialises_json_with_ttl() -> None:
    client = AsyncMock()
    cache = RedisStatusCache(client)
    await cache.set("svc", {"status": "healthy"}, ttl=45)
    client.set.assert_awaited_once_with(
        "capataz:status:svc", json.dumps({"status": "healthy"}), ex=45
    )
