"""
Unit tests for app/job_queue.py — Redis-backed job queue helpers.

Tests cover:
  - enqueue_job: DB row creation, Redis hash, Redis list push, queue-full 503
  - dequeue_job: returns job_id or None when empty
  - set_job_status: Redis hash update, DB sync, started_at / completed_at timestamps
  - get_job_status: returns dict or None
  - get_queue_depth: returns correct count

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 27.3, 27.4
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.job_queue import (
    MAX_QUEUE_DEPTH,
    QUEUE_KEY,
    JOB_HASH_PREFIX,
    dequeue_job,
    enqueue_job,
    get_job_status,
    get_queue_depth,
    set_job_status,
)
from app.videos import ProcessingJob, Video

# ---------------------------------------------------------------------------
# In-memory SQLite test database
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"

_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test."""
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    yield


@pytest.fixture
def db():
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


def _seed_video(db, video_id=None) -> Video:
    """Insert a minimal Video row into the test DB."""
    vid = Video(
        id=video_id or str(uuid.uuid4()),
        filename="test.mp4",
        filepath="data/videos/test.mp4",
        status="pending",
        upload_timestamp=datetime.now(timezone.utc),
        uploaded_by="user",
    )
    db.add(vid)
    db.commit()
    db.refresh(vid)
    return vid


def _make_redis_mock(queue_depth: int = 0) -> AsyncMock:
    """Return an AsyncMock that mimics the Redis client used by job_queue."""
    mock = AsyncMock()
    mock.llen = AsyncMock(return_value=queue_depth)
    mock.hset = AsyncMock(return_value=1)
    mock.rpush = AsyncMock(return_value=queue_depth + 1)
    mock.lpop = AsyncMock(return_value=None)
    mock.hgetall = AsyncMock(return_value={})
    return mock


# ---------------------------------------------------------------------------
# enqueue_job
# ---------------------------------------------------------------------------


class TestEnqueueJob:
    @pytest.mark.asyncio
    async def test_enqueue_creates_db_row_with_pending_status(self, db):
        """enqueue_job should insert a ProcessingJob row with status='pending'."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=0)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            job_id = await enqueue_job(video.id, db)

        job_row = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        assert job_row is not None
        assert job_row.status == "pending"
        assert job_row.video_id == video.id
        assert job_row.retry_count == 0

    @pytest.mark.asyncio
    async def test_enqueue_stores_redis_hash_with_pending_status(self, db):
        """enqueue_job should call hset with status='pending' in the hash mapping."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=0)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            job_id = await enqueue_job(video.id, db)

        # Verify hset was called with the correct hash key and status
        mock_redis.hset.assert_called_once()
        call_kwargs = mock_redis.hset.call_args
        hash_key = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("name", "")
        # hset(hash_key, mapping={...})
        mapping = call_kwargs[1].get("mapping") or (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        # Accept both positional and keyword call styles
        if not mapping:
            # Try keyword argument
            mapping = call_kwargs.kwargs.get("mapping", {})
        assert mapping.get("status") == "pending"
        assert mapping.get("job_id") == job_id
        assert mapping.get("video_id") == video.id

    @pytest.mark.asyncio
    async def test_enqueue_pushes_job_id_to_redis_list(self, db):
        """enqueue_job should call rpush with the job_id on the queue key."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=0)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            job_id = await enqueue_job(video.id, db)

        mock_redis.rpush.assert_called_once_with(QUEUE_KEY, job_id)

    @pytest.mark.asyncio
    async def test_enqueue_returns_job_id_string(self, db):
        """enqueue_job should return a non-empty string job_id."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=0)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            job_id = await enqueue_job(video.id, db)

        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @pytest.mark.asyncio
    async def test_enqueue_raises_503_when_queue_full(self, db):
        """enqueue_job should raise HTTP 503 when queue depth >= MAX_QUEUE_DEPTH."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=MAX_QUEUE_DEPTH)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await enqueue_job(video.id, db)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_enqueue_raises_503_when_queue_exceeds_max(self, db):
        """enqueue_job should raise HTTP 503 when queue depth > MAX_QUEUE_DEPTH."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=MAX_QUEUE_DEPTH + 5)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await enqueue_job(video.id, db)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_enqueue_succeeds_when_queue_one_below_max(self, db):
        """enqueue_job should succeed when queue depth is MAX_QUEUE_DEPTH - 1."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=MAX_QUEUE_DEPTH - 1)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            job_id = await enqueue_job(video.id, db)

        assert job_id is not None

    @pytest.mark.asyncio
    async def test_enqueue_does_not_push_when_queue_full(self, db):
        """When queue is full, rpush should NOT be called."""
        video = _seed_video(db)
        mock_redis = _make_redis_mock(queue_depth=MAX_QUEUE_DEPTH)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException):
                await enqueue_job(video.id, db)

        mock_redis.rpush.assert_not_called()


# ---------------------------------------------------------------------------
# dequeue_job
# ---------------------------------------------------------------------------


class TestDequeueJob:
    @pytest.mark.asyncio
    async def test_dequeue_returns_job_id_from_queue(self):
        """dequeue_job should return the job_id popped from the Redis list."""
        expected_job_id = str(uuid.uuid4())
        mock_redis = _make_redis_mock()
        mock_redis.lpop = AsyncMock(return_value=expected_job_id)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            result = await dequeue_job()

        assert result == expected_job_id
        mock_redis.lpop.assert_called_once_with(QUEUE_KEY)

    @pytest.mark.asyncio
    async def test_dequeue_returns_none_when_queue_empty(self):
        """dequeue_job should return None when the Redis list is empty."""
        mock_redis = _make_redis_mock()
        mock_redis.lpop = AsyncMock(return_value=None)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            result = await dequeue_job()

        assert result is None

    @pytest.mark.asyncio
    async def test_dequeue_calls_lpop_on_queue_key(self):
        """dequeue_job should call lpop with the correct queue key."""
        mock_redis = _make_redis_mock()
        mock_redis.lpop = AsyncMock(return_value=None)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            await dequeue_job()

        mock_redis.lpop.assert_called_once_with(QUEUE_KEY)


# ---------------------------------------------------------------------------
# set_job_status
# ---------------------------------------------------------------------------


class TestSetJobStatus:
    @pytest.mark.asyncio
    async def test_set_status_updates_redis_hash(self, db):
        """set_job_status should call hset with the new status."""
        job_id = str(uuid.uuid4())
        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job_id, "processing", db)

        mock_redis.hset.assert_called_once()
        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or (
            call_kwargs[1].get("mapping") if call_kwargs[1] else {}
        )
        assert mapping.get("status") == "processing"

    @pytest.mark.asyncio
    async def test_set_status_updates_db_row(self, db):
        """set_job_status should update the ProcessingJob row in the DB."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="pending",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "processing", db)

        db.refresh(job)
        assert job.status == "processing"

    @pytest.mark.asyncio
    async def test_set_status_sets_started_at_when_processing(self, db):
        """set_job_status should set started_at when status='processing'."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="pending",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "processing", db)

        db.refresh(job)
        assert job.started_at is not None

    @pytest.mark.asyncio
    async def test_set_status_sets_completed_at_when_completed(self, db):
        """set_job_status should set completed_at when status='completed'."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="processing",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "completed", db)

        db.refresh(job)
        assert job.completed_at is not None

    @pytest.mark.asyncio
    async def test_set_status_sets_completed_at_when_failed(self, db):
        """set_job_status should set completed_at when status='failed'."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="processing",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "failed", db, error_message="Pipeline error")

        db.refresh(job)
        assert job.completed_at is not None
        assert job.error_message == "Pipeline error"

    @pytest.mark.asyncio
    async def test_set_status_sets_completed_at_when_cancelled(self, db):
        """set_job_status should set completed_at when status='cancelled'."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="processing",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "cancelled", db)

        db.refresh(job)
        assert job.completed_at is not None

    @pytest.mark.asyncio
    async def test_set_status_does_not_set_started_at_for_non_processing(self, db):
        """set_job_status should NOT set started_at for statuses other than 'processing'."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="pending",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "completed", db)

        db.refresh(job)
        assert job.started_at is None

    @pytest.mark.asyncio
    async def test_set_status_updates_current_and_total_frames(self, db):
        """set_job_status should update current_frame and total_frames when provided."""
        video = _seed_video(db)
        job = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status="processing",
            retry_count=0,
        )
        db.add(job)
        db.commit()

        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job.id, "processing", db, current_frame=50, total_frames=200)

        db.refresh(job)
        assert job.current_frame == 50
        assert job.total_frames == 200

    @pytest.mark.asyncio
    async def test_set_status_includes_started_at_in_redis_hash(self, db):
        """set_job_status should include started_at in the Redis hash when processing."""
        job_id = str(uuid.uuid4())
        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job_id, "processing", db)

        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or (
            call_kwargs[1].get("mapping") if call_kwargs[1] else {}
        )
        assert "started_at" in mapping

    @pytest.mark.asyncio
    async def test_set_status_includes_completed_at_in_redis_hash(self, db):
        """set_job_status should include completed_at in the Redis hash for terminal statuses."""
        job_id = str(uuid.uuid4())
        mock_redis = _make_redis_mock()

        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(job_id, "completed", db)

        call_kwargs = mock_redis.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or (
            call_kwargs[1].get("mapping") if call_kwargs[1] else {}
        )
        assert "completed_at" in mapping

    @pytest.mark.asyncio
    async def test_set_status_gracefully_handles_missing_db_row(self, db):
        """set_job_status should not raise if the job row doesn't exist in DB."""
        non_existent_job_id = str(uuid.uuid4())
        mock_redis = _make_redis_mock()

        # Should not raise
        with patch("app.job_queue.get_redis", return_value=mock_redis), \
             patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock):
            await set_job_status(non_existent_job_id, "completed", db)

        mock_redis.hset.assert_called_once()


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_get_job_status_returns_dict_from_redis_hash(self):
        """get_job_status should return the Redis hash as a dict."""
        job_id = str(uuid.uuid4())
        expected_data = {
            "job_id": job_id,
            "video_id": "vid-123",
            "status": "processing",
            "retry_count": "0",
        }
        mock_redis = _make_redis_mock()
        mock_redis.hgetall = AsyncMock(return_value=expected_data)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            result = await get_job_status(job_id)

        assert result == expected_data
        mock_redis.hgetall.assert_called_once_with(f"{JOB_HASH_PREFIX}{job_id}")

    @pytest.mark.asyncio
    async def test_get_job_status_returns_none_for_unknown_job(self):
        """get_job_status should return None when the Redis hash is empty."""
        job_id = str(uuid.uuid4())
        mock_redis = _make_redis_mock()
        mock_redis.hgetall = AsyncMock(return_value={})

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            result = await get_job_status(job_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_status_uses_correct_hash_key(self):
        """get_job_status should query the hash key job:{job_id}."""
        job_id = "test-job-id"
        mock_redis = _make_redis_mock()
        mock_redis.hgetall = AsyncMock(return_value={"status": "pending"})

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            await get_job_status(job_id)

        mock_redis.hgetall.assert_called_once_with(f"job:{job_id}")


# ---------------------------------------------------------------------------
# get_queue_depth
# ---------------------------------------------------------------------------


class TestGetQueueDepth:
    @pytest.mark.asyncio
    async def test_get_queue_depth_returns_correct_count(self):
        """get_queue_depth should return the llen of the queue key."""
        mock_redis = _make_redis_mock()
        mock_redis.llen = AsyncMock(return_value=5)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            depth = await get_queue_depth()

        assert depth == 5
        mock_redis.llen.assert_called_once_with(QUEUE_KEY)

    @pytest.mark.asyncio
    async def test_get_queue_depth_returns_zero_when_empty(self):
        """get_queue_depth should return 0 when the queue is empty."""
        mock_redis = _make_redis_mock()
        mock_redis.llen = AsyncMock(return_value=0)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            depth = await get_queue_depth()

        assert depth == 0

    @pytest.mark.asyncio
    async def test_get_queue_depth_returns_max_queue_depth(self):
        """get_queue_depth should correctly return MAX_QUEUE_DEPTH."""
        mock_redis = _make_redis_mock()
        mock_redis.llen = AsyncMock(return_value=MAX_QUEUE_DEPTH)

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            depth = await get_queue_depth()

        assert depth == MAX_QUEUE_DEPTH


# ---------------------------------------------------------------------------
# Integration: enqueue → dequeue flow
# ---------------------------------------------------------------------------


class TestEnqueueDequeueFlow:
    @pytest.mark.asyncio
    async def test_enqueue_then_dequeue_returns_same_job_id(self, db):
        """Enqueuing a job and then dequeuing should return the same job_id."""
        video = _seed_video(db)
        enqueued_job_id = None

        # Capture the job_id passed to rpush
        captured_rpush_args = []

        async def mock_rpush(key, value):
            captured_rpush_args.append(value)
            return 1

        mock_redis = _make_redis_mock(queue_depth=0)
        mock_redis.rpush = mock_rpush

        with patch("app.job_queue.get_redis", return_value=mock_redis):
            enqueued_job_id = await enqueue_job(video.id, db)

        # Now simulate dequeue returning the same job_id
        mock_redis2 = _make_redis_mock()
        mock_redis2.lpop = AsyncMock(return_value=enqueued_job_id)

        with patch("app.job_queue.get_redis", return_value=mock_redis2):
            dequeued_job_id = await dequeue_job()

        assert dequeued_job_id == enqueued_job_id
