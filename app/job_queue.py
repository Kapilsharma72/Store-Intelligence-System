"""
Redis-backed job queue helpers for asynchronous video processing.

Provides:
  - enqueue_job(video_id, db)     — create a ProcessingJob row and push to Redis queue
  - dequeue_job()                 — pop a job_id from the Redis queue (non-blocking)
  - set_job_status(...)           — update job status in Redis hash and DB
  - get_job_status(job_id)        — retrieve job metadata from Redis hash
  - get_queue_depth()             — return current number of pending jobs in the queue

Requirements: 4.1, 4.2, 27.3, 27.4
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.redis_client import cache_invalidate_pattern, get_redis
from app.videos import ProcessingJob

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUEUE_KEY = "job_queue"
JOB_HASH_PREFIX = "job:"
MAX_QUEUE_DEPTH = 10


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def enqueue_job(video_id: str, db: Session) -> str:
    """
    Create a ProcessingJob row in the database with status "pending", store job
    metadata as a Redis hash, and push the job_id onto the Redis queue.

    Raises HTTP 503 if the queue already has MAX_QUEUE_DEPTH or more pending jobs.

    Returns the new job_id.

    Requirements: 4.1, 4.2, 27.3, 27.4
    """
    redis = get_redis()

    # Check queue depth before enqueuing (Requirement 27.4)
    depth = await redis.llen(QUEUE_KEY)
    if depth >= MAX_QUEUE_DEPTH:
        logger.warning(
            "job_queue_full",
            queue_depth=depth,
            max_queue_depth=MAX_QUEUE_DEPTH,
            video_id=video_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Job queue is full ({depth} pending jobs). "
                "Please retry later."
            ),
        )

    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    enqueued_at = now.isoformat()

    # Persist ProcessingJob row to the database (Requirement 4.2)
    job_row = ProcessingJob(
        id=job_id,
        video_id=video_id,
        status="pending",
        retry_count=0,
    )
    db.add(job_row)
    db.commit()
    db.refresh(job_row)

    # Store job metadata as a Redis hash (Requirement 4.2)
    hash_key = f"{JOB_HASH_PREFIX}{job_id}"
    await redis.hset(
        hash_key,
        mapping={
            "job_id": job_id,
            "video_id": video_id,
            "status": "pending",
            "retry_count": "0",
            "enqueued_at": enqueued_at,
        },
    )

    # Push job_id to the right end of the Redis list (Requirement 4.1, 27.3)
    await redis.rpush(QUEUE_KEY, job_id)

    logger.info(
        "job_enqueued",
        job_id=job_id,
        video_id=video_id,
        queue_depth=depth + 1,
    )

    return job_id


async def dequeue_job() -> Optional[str]:
    """
    Pop a job_id from the left of the Redis queue (non-blocking).

    Returns the job_id string, or None if the queue is empty.

    Requirements: 4.3
    """
    redis = get_redis()
    job_id = await redis.lpop(QUEUE_KEY)
    if job_id:
        logger.info("job_dequeued", job_id=job_id)
    return job_id


async def set_job_status(
    job_id: str,
    status: str,
    db: Session,
    current_frame: Optional[int] = None,
    total_frames: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Update the job status in both the Redis hash and the ProcessingJob DB row.

    - If status is "processing", sets started_at to now.
    - If status is "completed", "failed", or "cancelled", sets completed_at to now.

    Requirements: 4.3, 4.4, 4.5
    """
    redis = get_redis()
    now = datetime.now(timezone.utc)

    # Build Redis hash update fields
    hash_fields: dict = {"status": status}
    if current_frame is not None:
        hash_fields["current_frame"] = str(current_frame)
    if total_frames is not None:
        hash_fields["total_frames"] = str(total_frames)
    if error_message is not None:
        hash_fields["error_message"] = error_message

    terminal_statuses = {"completed", "failed", "cancelled"}

    if status == "processing":
        hash_fields["started_at"] = now.isoformat()
    if status in terminal_statuses:
        hash_fields["completed_at"] = now.isoformat()

    hash_key = f"{JOB_HASH_PREFIX}{job_id}"
    await redis.hset(hash_key, mapping=hash_fields)

    # Sync to the database
    job_row = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if job_row is not None:
        video_id = job_row.video_id
        job_row.status = status
        if current_frame is not None:
            job_row.current_frame = current_frame
        if total_frames is not None:
            job_row.total_frames = total_frames
        if error_message is not None:
            job_row.error_message = error_message
        if status == "processing":
            job_row.started_at = now
        if status in terminal_statuses:
            job_row.completed_at = now
        db.commit()

        # Invalidate cached analytics whenever processing status changes (Requirement 29.4)
        await cache_invalidate_pattern(f"analytics:{video_id}:*")

    logger.info(
        "job_status_updated",
        job_id=job_id,
        status=status,
        current_frame=current_frame,
        total_frames=total_frames,
    )

async def get_job_status(job_id: str) -> Optional[dict]:
    """
    Return the Redis hash for job:{job_id} as a dict, or None if not found.

    Requirements: 4.2
    """
    redis = get_redis()
    hash_key = f"{JOB_HASH_PREFIX}{job_id}"
    data = await redis.hgetall(hash_key)
    if not data:
        return None
    return data


async def get_queue_depth() -> int:
    """
    Return the current number of jobs in the Redis queue (LLEN of job_queue).

    Requirements: 27.4
    """
    redis = get_redis()
    return await redis.llen(QUEUE_KEY)
