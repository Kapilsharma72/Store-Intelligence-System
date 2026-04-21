"""
Unit tests for app/rate_limit.py — sliding-window upload rate limiting.

Tests cover:
  - First 10 uploads succeed (within limit)
  - 11th upload returns HTTP 429 with Retry-After header
  - Admin user is exempt from rate limiting
  - Redis unavailability allows request through (fail open)

Requirements: 18.1, 18.2, 18.3, 18.5
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError

from app.auth import UserContext
from app.rate_limit import (
    UPLOAD_RATE_LIMIT,
    UPLOAD_RATE_WINDOW_SECONDS,
    check_upload_rate_limit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis_mock(existing_count: int = 0, oldest_score: float | None = None):
    """
    Build an AsyncMock Redis client that simulates a sorted set with
    *existing_count* entries already in the window.
    """
    mock = AsyncMock()
    mock.zremrangebyscore = AsyncMock(return_value=None)
    mock.zcard = AsyncMock(return_value=existing_count)
    mock.zadd = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)

    if oldest_score is not None:
        # zrange returns list of (member, score) tuples when withscores=True
        mock.zrange = AsyncMock(return_value=[("some-id", oldest_score)])
    else:
        mock.zrange = AsyncMock(return_value=[])

    return mock


async def _call_dependency(user: UserContext, redis_mock) -> None:
    """Drive the check_upload_rate_limit dependency to completion."""
    gen = check_upload_rate_limit.__wrapped__ if hasattr(check_upload_rate_limit, "__wrapped__") else None
    # Call the function directly (it's a plain async function, not a generator)
    await check_upload_rate_limit(current_user=user, redis_client=redis_mock)


# ---------------------------------------------------------------------------
# Tests: normal user within limit
# ---------------------------------------------------------------------------


class TestRateLimitWithinLimit:
    @pytest.mark.asyncio
    async def test_first_upload_succeeds(self):
        """First upload (count=0) should pass without raising."""
        user = UserContext(username="alice", role="user")
        redis_mock = _make_redis_mock(existing_count=0)

        # Should not raise
        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        # Verify the entry was recorded
        redis_mock.zadd.assert_awaited_once()
        redis_mock.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tenth_upload_succeeds(self):
        """10th upload (count=9 before this one) should still pass."""
        user = UserContext(username="alice", role="user")
        redis_mock = _make_redis_mock(existing_count=UPLOAD_RATE_LIMIT - 1)

        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        redis_mock.zadd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_old_entries_are_pruned(self):
        """zremrangebyscore should be called to prune expired entries."""
        user = UserContext(username="alice", role="user")
        redis_mock = _make_redis_mock(existing_count=0)

        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        redis_mock.zremrangebyscore.assert_awaited_once()
        # Verify the key format
        call_args = redis_mock.zremrangebyscore.call_args
        assert call_args[0][0] == f"rate_limit:upload:{user.username}"

    @pytest.mark.asyncio
    async def test_key_expiry_is_set(self):
        """expire() should be called with the window duration."""
        user = UserContext(username="bob", role="user")
        redis_mock = _make_redis_mock(existing_count=0)

        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        redis_mock.expire.assert_awaited_once()
        call_args = redis_mock.expire.call_args
        assert call_args[0][1] == UPLOAD_RATE_WINDOW_SECONDS


# ---------------------------------------------------------------------------
# Tests: limit exceeded
# ---------------------------------------------------------------------------


class TestRateLimitExceeded:
    @pytest.mark.asyncio
    async def test_eleventh_upload_raises_429(self):
        """11th upload (count=10) should raise HTTP 429."""
        user = UserContext(username="alice", role="user")
        oldest_score = time.time() - 100  # 100 seconds ago
        redis_mock = _make_redis_mock(
            existing_count=UPLOAD_RATE_LIMIT,
            oldest_score=oldest_score,
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_429_includes_retry_after_header(self):
        """HTTP 429 response must include a Retry-After header."""
        user = UserContext(username="alice", role="user")
        oldest_score = time.time() - 100  # 100 seconds ago → ~3500 s remaining
        redis_mock = _make_redis_mock(
            existing_count=UPLOAD_RATE_LIMIT,
            oldest_score=oldest_score,
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        headers = exc_info.value.headers
        assert headers is not None
        assert "Retry-After" in headers
        retry_after = int(headers["Retry-After"])
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_retry_after_value_is_correct(self):
        """Retry-After should equal seconds until the oldest entry expires."""
        user = UserContext(username="alice", role="user")
        now = time.time()
        age_seconds = 200  # oldest entry is 200 s old → 3400 s remaining
        oldest_score = now - age_seconds
        redis_mock = _make_redis_mock(
            existing_count=UPLOAD_RATE_LIMIT,
            oldest_score=oldest_score,
        )

        with patch("app.rate_limit.time") as mock_time:
            mock_time.time.return_value = now
            with pytest.raises(HTTPException) as exc_info:
                await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        expected = int(oldest_score + UPLOAD_RATE_WINDOW_SECONDS - now)
        actual = int(exc_info.value.headers["Retry-After"])
        assert actual == expected

    @pytest.mark.asyncio
    async def test_no_zadd_when_limit_exceeded(self):
        """When the limit is exceeded, no new entry should be recorded."""
        user = UserContext(username="alice", role="user")
        redis_mock = _make_redis_mock(
            existing_count=UPLOAD_RATE_LIMIT,
            oldest_score=time.time() - 50,
        )

        with pytest.raises(HTTPException):
            await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        redis_mock.zadd.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: admin exemption
# ---------------------------------------------------------------------------


class TestAdminExemption:
    @pytest.mark.asyncio
    async def test_admin_bypasses_rate_limit(self):
        """Admin users should never be rate-limited, even at count=100."""
        user = UserContext(username="admin", role="admin")
        redis_mock = _make_redis_mock(existing_count=100)

        # Should not raise
        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

    @pytest.mark.asyncio
    async def test_admin_does_not_touch_redis(self):
        """Admin bypass should short-circuit before any Redis calls."""
        user = UserContext(username="admin", role="admin")
        redis_mock = _make_redis_mock(existing_count=100)

        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

        redis_mock.zremrangebyscore.assert_not_awaited()
        redis_mock.zcard.assert_not_awaited()
        redis_mock.zadd.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: Redis unavailability (fail open)
# ---------------------------------------------------------------------------


class TestRedisFailOpen:
    @pytest.mark.asyncio
    async def test_redis_connection_error_allows_request(self):
        """When Redis raises ConnectionError, the request should be allowed through."""
        user = UserContext(username="alice", role="user")
        redis_mock = AsyncMock()
        redis_mock.zremrangebyscore = AsyncMock(
            side_effect=RedisConnectionError("Connection refused")
        )

        # Should not raise — fail open
        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

    @pytest.mark.asyncio
    async def test_redis_generic_error_allows_request(self):
        """When Redis raises a generic RedisError, the request should be allowed through."""
        from redis.exceptions import RedisError

        user = UserContext(username="alice", role="user")
        redis_mock = AsyncMock()
        redis_mock.zremrangebyscore = AsyncMock(
            side_effect=RedisError("Unexpected error")
        )

        # Should not raise — fail open
        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)

    @pytest.mark.asyncio
    async def test_redis_error_on_zadd_allows_request(self):
        """Even if zadd fails, the request should be allowed through."""
        from redis.exceptions import RedisError

        user = UserContext(username="alice", role="user")
        redis_mock = _make_redis_mock(existing_count=0)
        redis_mock.zadd = AsyncMock(side_effect=RedisError("Write failed"))

        # Should not raise — fail open
        await check_upload_rate_limit(current_user=user, redis_client=redis_mock)
