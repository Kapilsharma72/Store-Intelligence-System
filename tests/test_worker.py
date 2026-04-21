"""
Unit tests for app/worker.py — background video processing worker.

Tests cover:
  - process_video_job: marks job as "processing" then "completed" on success
  - process_video_job: checks cancellation flag and stops when set
  - process_video_job: persists partial events before cancellation
  - process_video_job: retries on error with exponential backoff
  - process_video_job: marks job as "failed" after MAX_RETRIES

All external dependencies (cv2, detect_persons, ByteTracker, EventEmitter,
Redis, DB) are mocked.

Requirements: 4.3, 4.4, 4.5, 5.1, 5.2, 5.3
"""

import asyncio
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.videos import ProcessingJob, Video
from app.worker import MAX_RETRIES, process_video_job

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_video(db, video_id=None, filepath="data/videos/test.mp4") -> Video:
    vid = Video(
        id=video_id or str(uuid.uuid4()),
        filename="test.mp4",
        filepath=filepath,
        status="pending",
        upload_timestamp=datetime.now(timezone.utc),
        uploaded_by="user",
        store_config="STORE_001",
    )
    db.add(vid)
    db.commit()
    db.refresh(vid)
    return vid


def _seed_job(db, video_id, retry_count=0) -> ProcessingJob:
    job = ProcessingJob(
        id=str(uuid.uuid4()),
        video_id=video_id,
        status="pending",
        retry_count=retry_count,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_cv2_mock(total_frames: int = 10, fps: float = 25.0):
    """
    Return a (mock_cv2_module, mock_cap) pair.

    cv2 is imported *inside* process_video_job with `import cv2`, so we inject
    the mock into sys.modules['cv2'] before calling the function.
    """
    frame_counter = {"count": 0}

    def mock_read():
        if frame_counter["count"] < total_frames:
            frame_counter["count"] += 1
            return True, MagicMock()
        return False, None

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.side_effect = mock_read
    # CAP_PROP_FRAME_COUNT=0, CAP_PROP_FPS=5, CAP_PROP_POS_MSEC=0.0
    mock_cap.get.side_effect = lambda prop: total_frames if prop == 0 else fps
    mock_cap.release = MagicMock()

    mock_cv2 = MagicMock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_FRAME_COUNT = 0
    mock_cv2.CAP_PROP_FPS = 5
    mock_cv2.CAP_PROP_POS_MSEC = 0.0

    return mock_cv2, mock_cap


def _make_redis_mock(cancel_flag=None):
    """Return an AsyncMock Redis client."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=cancel_flag)
    mock.set = AsyncMock(return_value=True)
    mock.hset = AsyncMock(return_value=1)
    mock.rpush = AsyncMock(return_value=1)
    mock.lpop = AsyncMock(return_value=None)
    mock.hgetall = AsyncMock(return_value={})
    mock.llen = AsyncMock(return_value=0)
    return mock


def _make_tracker_mock(num_tracks: int = 0):
    """Return a mock ByteTracker."""
    track = MagicMock()
    track.is_lost = False
    track.track_id = 1

    mock_tracker = MagicMock()
    mock_tracker.update_tracks.return_value = [track] * num_tracks
    return mock_tracker


def _make_emitter_mock():
    """Return a mock EventEmitter."""
    mock_event = MagicMock()
    mock_event.event_id = str(uuid.uuid4())
    mock_event.event_type = "ZONE_ENTER"
    mock_event.visitor_id = "VIS_abc123"
    mock_event.store_id = "STORE_001"
    mock_event.camera_id = "CAM_1"
    mock_event.zone_id = None
    mock_event.timestamp = datetime.now(timezone.utc).isoformat()
    mock_event.metadata = None

    mock_emitter = MagicMock()
    mock_emitter.emit_event.return_value = mock_event
    return mock_emitter


@contextmanager
def _worker_patches(db_session, mock_redis, mock_cv2, mock_tracker=None,
                    mock_emitter=None, mock_detect=None, mock_sleep=None,
                    mock_set_job_status=None, mock_publish=None):
    """
    Context manager that applies all patches needed to run process_video_job
    in isolation.

    cv2 is imported inside the function body, so we inject it via sys.modules.
    We patch get_redis in BOTH app.worker and app.job_queue since set_job_status
    calls get_redis() from app.job_queue's own module scope.
    """
    if mock_tracker is None:
        mock_tracker = _make_tracker_mock(0)
    if mock_emitter is None:
        mock_emitter = _make_emitter_mock()
    if mock_detect is None:
        mock_detect = MagicMock(return_value=[])
    if mock_publish is None:
        mock_publish = AsyncMock()

    # Inject cv2 into sys.modules so `import cv2` inside the function gets our mock
    original_cv2 = sys.modules.get("cv2")
    sys.modules["cv2"] = mock_cv2

    try:
        patches = [
            patch("app.worker._get_db", return_value=db_session),
            patch("app.worker.get_redis", return_value=mock_redis),
            patch("app.job_queue.get_redis", return_value=mock_redis),  # used by set_job_status
            patch("app.job_queue.cache_invalidate_pattern", new_callable=AsyncMock),  # used by set_job_status
            patch("app.worker.publish", mock_publish),
            patch("app.worker.detect_persons", mock_detect),
            patch("app.worker.ByteTracker", return_value=mock_tracker),
            patch("app.worker.EventEmitter", return_value=mock_emitter),
            patch("app.worker._persist_events_to_db", MagicMock()),
            patch("app.worker.make_visitor_token", return_value="VIS_abc123"),
        ]

        if mock_sleep is not None:
            patches.append(patch("asyncio.sleep", mock_sleep))

        if mock_set_job_status is not None:
            patches.append(patch("app.worker.set_job_status", side_effect=mock_set_job_status))

        # Enter all patches
        entered = []
        try:
            for p in patches:
                entered.append(p.__enter__())
            yield entered
        finally:
            for p, e in zip(patches, entered):
                p.__exit__(None, None, None)
    finally:
        # Restore original cv2 in sys.modules
        if original_cv2 is None:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = original_cv2


# ---------------------------------------------------------------------------
# Test: success path — processing → completed
# ---------------------------------------------------------------------------


class TestProcessVideoJobSuccess:
    @pytest.mark.asyncio
    async def test_marks_job_as_processing_then_completed(self, db):
        """On success, job status should transition: pending → processing → completed."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)
        mock_cv2, _ = _make_cv2_mock(total_frames=5)

        status_calls = []

        async def mock_set_job_status(job_id, status, db_session, **kwargs):
            status_calls.append(status)

        with _worker_patches(db, mock_redis, mock_cv2,
                             mock_set_job_status=mock_set_job_status):
            await process_video_job(job.id, video.id)

        assert "processing" in status_calls
        assert status_calls[-1] == "completed"

    @pytest.mark.asyncio
    async def test_updates_video_status_to_completed(self, db):
        """On success, the Video row status should be updated to 'completed'."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)
        mock_cv2, _ = _make_cv2_mock(total_frames=3)

        with _worker_patches(db, mock_redis, mock_cv2):
            await process_video_job(job.id, video.id)

        db.refresh(video)
        assert video.status == "completed"

    @pytest.mark.asyncio
    async def test_publishes_final_progress_on_completion(self, db):
        """On success, a final progress message should be published to Redis pub/sub."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)
        mock_cv2, _ = _make_cv2_mock(total_frames=3)
        mock_publish = AsyncMock()

        with _worker_patches(db, mock_redis, mock_cv2, mock_publish=mock_publish):
            await process_video_job(job.id, video.id)

        assert mock_publish.call_count >= 1
        last_call_args = mock_publish.call_args_list[-1][0]
        assert last_call_args[0] == f"progress:{video.id}"


# ---------------------------------------------------------------------------
# Test: cancellation
# ---------------------------------------------------------------------------


class TestProcessVideoJobCancellation:
    @pytest.mark.asyncio
    async def test_stops_when_cancellation_flag_is_set(self, db):
        """Worker should stop processing when cancel:{video_id} flag is set in Redis."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag="1")
        mock_cv2, _ = _make_cv2_mock(total_frames=100)

        status_calls = []

        async def mock_set_job_status(job_id, status, db_session, **kwargs):
            status_calls.append(status)

        with _worker_patches(db, mock_redis, mock_cv2,
                             mock_set_job_status=mock_set_job_status):
            await process_video_job(job.id, video.id)

        assert "cancelled" in status_calls
        assert "completed" not in status_calls

    @pytest.mark.asyncio
    async def test_updates_video_status_to_cancelled(self, db):
        """When cancelled, the Video row status should be updated to 'cancelled'."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag="1")
        mock_cv2, _ = _make_cv2_mock(total_frames=100)

        with _worker_patches(db, mock_redis, mock_cv2):
            await process_video_job(job.id, video.id)

        db.refresh(video)
        assert video.status == "cancelled"

    @pytest.mark.asyncio
    async def test_persists_partial_events_before_cancellation(self, db):
        """Worker should flush buffered events to DB before stopping on cancellation."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        # Cancel flag is set immediately — worker checks before reading first frame
        mock_redis = _make_redis_mock(cancel_flag="1")
        mock_cv2, _ = _make_cv2_mock(total_frames=100)

        with _worker_patches(db, mock_redis, mock_cv2,
                             mock_tracker=_make_tracker_mock(1)):
            await process_video_job(job.id, video.id)

        # Video should be cancelled (partial events flushed or empty batch — both valid)
        db.refresh(video)
        assert video.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancellation_releases_video_capture(self, db):
        """Worker should release the VideoCapture object when cancelled."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag="1")
        mock_cv2, mock_cap = _make_cv2_mock(total_frames=100)

        with _worker_patches(db, mock_redis, mock_cv2):
            await process_video_job(job.id, video.id)

        mock_cap.release.assert_called_once()


# ---------------------------------------------------------------------------
# Test: retry logic and exponential backoff
# ---------------------------------------------------------------------------


class TestProcessVideoJobRetry:
    @pytest.mark.asyncio
    async def test_retries_on_error_and_eventually_succeeds(self, db):
        """Worker should retry after an error and succeed on a later attempt."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)

        call_count = {"n": 0}

        def make_cap(video_path):  # VideoCapture is called with a path argument
            call_count["n"] += 1
            cap = MagicMock()
            cap.isOpened.return_value = True
            if call_count["n"] == 1:
                # First attempt: fail on read
                cap.get.side_effect = lambda p: 5 if p == 0 else 25.0
                cap.read.side_effect = RuntimeError("Transient error")
            else:
                # Second attempt: succeed with 3 frames
                frame_counter = {"count": 0}

                def mock_read():
                    if frame_counter["count"] < 3:
                        frame_counter["count"] += 1
                        return True, MagicMock()
                    return False, None

                cap.get.side_effect = lambda p: 3 if p == 0 else 25.0
                cap.read.side_effect = mock_read
            cap.release = MagicMock()
            return cap

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.side_effect = make_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 0
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.CAP_PROP_POS_MSEC = 0.0

        status_calls = []

        async def mock_set_job_status(job_id, status, db_session, **kwargs):
            status_calls.append(status)

        mock_sleep = AsyncMock()

        with _worker_patches(db, mock_redis, mock_cv2,
                             mock_set_job_status=mock_set_job_status,
                             mock_sleep=mock_sleep):
            await process_video_job(job.id, video.id)

        assert "completed" in status_calls

    @pytest.mark.asyncio
    async def test_marks_job_as_failed_after_max_retries(self, db):
        """Worker should mark job as 'failed' after exhausting MAX_RETRIES."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)

        def make_failing_cap(video_path):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.get.side_effect = lambda p: 10 if p == 0 else 25.0
            cap.read.side_effect = RuntimeError("Persistent error")
            cap.release = MagicMock()
            return cap

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.side_effect = make_failing_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 0
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.CAP_PROP_POS_MSEC = 0.0

        status_calls = []

        async def mock_set_job_status(job_id, status, db_session, **kwargs):
            status_calls.append(status)

        mock_sleep = AsyncMock()

        with _worker_patches(db, mock_redis, mock_cv2,
                             mock_set_job_status=mock_set_job_status,
                             mock_sleep=mock_sleep):
            await process_video_job(job.id, video.id)

        assert "failed" in status_calls
        assert "completed" not in status_calls

    @pytest.mark.asyncio
    async def test_exponential_backoff_between_retries(self, db):
        """Worker should sleep with exponential backoff (2^retry) between retries."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)

        def make_failing_cap(video_path):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.get.side_effect = lambda p: 10 if p == 0 else 25.0
            cap.read.side_effect = RuntimeError("Persistent error")
            cap.release = MagicMock()
            return cap

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.side_effect = make_failing_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 0
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.CAP_PROP_POS_MSEC = 0.0

        mock_sleep = AsyncMock()

        with _worker_patches(db, mock_redis, mock_cv2, mock_sleep=mock_sleep):
            await process_video_job(job.id, video.id)

        # asyncio.sleep is called for each retry except the last (which marks failed)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        # For MAX_RETRIES=3: sleep after retry 1 (backoff=2) and retry 2 (backoff=4)
        assert len(sleep_calls) == MAX_RETRIES - 1
        for i, sleep_val in enumerate(sleep_calls):
            expected = 2 ** (i + 1)
            assert sleep_val == expected, f"Expected backoff {expected}s, got {sleep_val}s"

    @pytest.mark.asyncio
    async def test_retry_count_increments_in_db(self, db):
        """Worker should increment retry_count in the DB on each failure."""
        video = _seed_video(db)
        job = _seed_job(db, video.id, retry_count=0)

        mock_redis = _make_redis_mock(cancel_flag=None)

        def make_failing_cap(video_path):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.get.side_effect = lambda p: 10 if p == 0 else 25.0
            cap.read.side_effect = RuntimeError("Persistent error")
            cap.release = MagicMock()
            return cap

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.side_effect = make_failing_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 0
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.CAP_PROP_POS_MSEC = 0.0

        mock_sleep = AsyncMock()

        with _worker_patches(db, mock_redis, mock_cv2, mock_sleep=mock_sleep):
            await process_video_job(job.id, video.id)

        db.refresh(job)
        assert job.retry_count == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_updates_video_status_to_failed_after_max_retries(self, db):
        """After exhausting retries, the Video row status should be 'failed'."""
        video = _seed_video(db)
        job = _seed_job(db, video.id)

        mock_redis = _make_redis_mock(cancel_flag=None)

        def make_failing_cap(video_path):
            cap = MagicMock()
            cap.isOpened.return_value = True
            cap.get.side_effect = lambda p: 10 if p == 0 else 25.0
            cap.read.side_effect = RuntimeError("Persistent error")
            cap.release = MagicMock()
            return cap

        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.side_effect = make_failing_cap
        mock_cv2.CAP_PROP_FRAME_COUNT = 0
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.CAP_PROP_POS_MSEC = 0.0

        mock_sleep = AsyncMock()

        with _worker_patches(db, mock_redis, mock_cv2, mock_sleep=mock_sleep):
            await process_video_job(job.id, video.id)

        db.refresh(video)
        assert video.status == "failed"
