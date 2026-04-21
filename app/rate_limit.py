"""
Rate limiting dependency for the video upload endpoint.

Implements a sliding-window algorithm using a Redis sorted set:
  - Key: rate_limit:upload:{username}
  - Members: unique request IDs
  - Scores: Unix timestamps of each request

Limit: 10 uploads per hour (3600 seconds).
Admin users are exempt from rate limiting.
If Redis is unavailable, the request is allowed through (fail open).

Requirements: 18.1, 18.2, 18.3, 18.5
"""

import time
import uuid
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.auth import UserContext, get_current_user
from app.redis_client import get_redis_dep

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UPLOAD_RATE_LIMIT = 10          # maximum uploads per window
UPLOAD_RATE_WINDOW_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def check_upload_rate_limit(
    current_user: Annotated[UserContext, Depends(get_current_user)],
    redis_client: Annotated[Redis, Depends(get_redis_dep)],
) -> None:
    """
    FastAPI dependency that enforces the sliding-window upload rate limit.

    - Admin users bypass the limit entirely.
    - On Redis failure the request is allowed through (fail open).
    - Raises HTTP 429 with Retry-After header when the limit is exceeded.

    Requirements: 18.1, 18.2, 18.3, 18.5
    """
    # Admins are exempt (Requirement 18.5)
    if current_user.role == "admin":
        return

    key = f"rate_limit:upload:{current_user.username}"
    now = time.time()
    window_start = now - UPLOAD_RATE_WINDOW_SECONDS

    try:
        # 1. Remove entries older than the window
        await redis_client.zremrangebyscore(key, "-inf", window_start)

        # 2. Count remaining entries in the window
        count = await redis_client.zcard(key)

        # 3. Enforce the limit
        if count >= UPLOAD_RATE_LIMIT:
            # Compute Retry-After: seconds until the oldest entry expires
            oldest = await redis_client.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_score = oldest[0][1]
                retry_after = int(oldest_score + UPLOAD_RATE_WINDOW_SECONDS - now)
                retry_after = max(retry_after, 1)
            else:
                retry_after = UPLOAD_RATE_WINDOW_SECONDS

            logger.warning(
                "upload_rate_limit_exceeded",
                username=current_user.username,
                count=count,
                retry_after=retry_after,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Upload rate limit exceeded. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

        # 4. Record this request and set key expiry
        request_id = str(uuid.uuid4())
        await redis_client.zadd(key, {request_id: now})
        await redis_client.expire(key, UPLOAD_RATE_WINDOW_SECONDS)

    except HTTPException:
        raise
    except RedisError as exc:
        # Fail open: log a warning and allow the request through
        logger.warning(
            "rate_limit_redis_unavailable",
            username=current_user.username,
            error=str(exc),
        )
