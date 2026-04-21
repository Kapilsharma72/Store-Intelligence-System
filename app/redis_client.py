import os
from typing import Optional

import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------
_pool: Optional[aioredis.ConnectionPool] = None


def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            REDIS_URL,
            decode_responses=True,
        )
    return _pool


def get_redis() -> aioredis.Redis:
    """Return an async Redis client backed by the shared connection pool."""
    return aioredis.Redis(connection_pool=_get_pool())


async def get_redis_dep() -> aioredis.Redis:
    """FastAPI dependency that yields an async Redis client."""
    yield get_redis()


# ---------------------------------------------------------------------------
# Pub/Sub helpers
# ---------------------------------------------------------------------------
async def publish(channel: str, message: str) -> None:
    """Publish *message* to *channel*."""
    async with get_redis() as client:
        await client.publish(channel, message)


async def subscribe(channel: str) -> aioredis.client.PubSub:
    """Return a PubSub object already subscribed to *channel*."""
    client = get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    return pubsub


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
async def cache_get(key: str) -> Optional[str]:
    """Return the cached value for *key*, or None if missing / expired."""
    async with get_redis() as client:
        return await client.get(key)


async def cache_set(key: str, value: str, ttl_seconds: int = 3600) -> None:
    """Store *value* under *key* with an expiry of *ttl_seconds*."""
    async with get_redis() as client:
        await client.set(key, value, ex=ttl_seconds)


async def cache_invalidate(key: str) -> None:
    """Delete a single cache *key*."""
    async with get_redis() as client:
        await client.delete(key)


async def cache_invalidate_pattern(pattern: str) -> None:
    """Delete all keys matching *pattern* (uses SCAN to avoid blocking)."""
    async with get_redis() as client:
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
