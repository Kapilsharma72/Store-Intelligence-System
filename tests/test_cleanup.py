"""
Unit tests for app/cleanup.py — storage cleanup logic.

Tests exercise run_cleanup() directly (not the scheduler) using an in-memory
SQLite database and a mock storage backend.

Requirements: 19.1, 19.2, 19.3, 19.4
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.videos import ProcessingJob, Video


# ---------------------------------------------------------------------------
# In-memory DB setup
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_video(db, days_old: int, video_id: str | None = None) -> Video:
    """Insert a Video row with upload_timestamp set *days_old* days in the past."""
    vid = Video(
        id=video_id or str(uuid.uuid4()),
        filename=f"cam_{days_old}d.mp4",
        filepath=f"data/videos/{video_id or 'x'}/cam_{days_old}d.mp4",
        duration_seconds=60.0,
        resolution="1920x1080",
        codec="h264",
        file_size_bytes=1024,
        store_config="STORE_001",
        status="completed",
        upload_timestamp=datetime.now(timezone.utc) - timedelta(days=days_old),
        uploaded_by="testuser",
    )
    db.add(vid)
    db.commit()
    db.refresh(vid)
    return vid


def _make_job(db, video_id: str) -> ProcessingJob:
    job = ProcessingJob(
        id=str(uuid.uuid4()),
        video_id=video_id,
        status="completed",
        current_frame=100,
        total_frames=100,
    )
    db.add(job)
    db.commit()
    return job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_deletes_expired_videos(db):
    """Videos older than retention_days are deleted from DB and storage."""
    old_video = _make_video(db, days_old=100)
    _make_job(db, old_video.id)

    mock_storage = AsyncMock()
    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup
        deleted = await run_cleanup(db, retention_days=90)

    assert deleted == 1
    mock_storage.delete_video.assert_awaited_once_with(old_video.id, old_video.filepath)
    assert db.query(Video).filter(Video.id == old_video.id).first() is None
    assert db.query(ProcessingJob).filter(ProcessingJob.video_id == old_video.id).first() is None


@pytest.mark.asyncio
async def test_cleanup_preserves_recent_videos(db):
    """Videos within the retention window are NOT deleted."""
    recent_video = _make_video(db, days_old=10)

    mock_storage = AsyncMock()
    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup
        deleted = await run_cleanup(db, retention_days=90)

    assert deleted == 0
    mock_storage.delete_video.assert_not_awaited()
    assert db.query(Video).filter(Video.id == recent_video.id).first() is not None


@pytest.mark.asyncio
async def test_cleanup_mixed_ages(db):
    """Only expired videos are deleted; recent ones survive."""
    old_video = _make_video(db, days_old=91)
    recent_video = _make_video(db, days_old=30)

    mock_storage = AsyncMock()
    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup
        deleted = await run_cleanup(db, retention_days=90)

    assert deleted == 1
    assert db.query(Video).filter(Video.id == old_video.id).first() is None
    assert db.query(Video).filter(Video.id == recent_video.id).first() is not None


@pytest.mark.asyncio
async def test_cleanup_empty_db(db):
    """No videos in DB — cleanup returns 0 without errors."""
    mock_storage = AsyncMock()
    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup
        deleted = await run_cleanup(db, retention_days=90)

    assert deleted == 0
    mock_storage.delete_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_continues_on_storage_error(db):
    """If file deletion fails, the DB record is still removed."""
    old_video = _make_video(db, days_old=100)

    mock_storage = AsyncMock()
    mock_storage.delete_video.side_effect = OSError("disk error")

    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup
        deleted = await run_cleanup(db, retention_days=90)

    # DB row should still be deleted despite storage error
    assert deleted == 1
    assert db.query(Video).filter(Video.id == old_video.id).first() is None


@pytest.mark.asyncio
async def test_cleanup_logs_each_deletion(db, caplog):
    """Each deleted video is logged with video_id, filename, and timestamp."""
    import logging
    old_video = _make_video(db, days_old=100)

    mock_storage = AsyncMock()
    log_calls = []

    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        with patch("app.cleanup.logger") as mock_logger:
            from app.cleanup import run_cleanup
            await run_cleanup(db, retention_days=90)
            # Find the cleanup_video_deleted call
            info_calls = [
                call for call in mock_logger.info.call_args_list
                if call.args and call.args[0] == "cleanup_video_deleted"
            ]
            assert len(info_calls) == 1
            kwargs = info_calls[0].kwargs
            assert kwargs["video_id"] == old_video.id
            assert kwargs["filename"] == old_video.filename
            assert "deletion_timestamp" in kwargs


@pytest.mark.asyncio
async def test_cleanup_respects_custom_retention_days(db):
    """Custom retention_days parameter is respected."""
    # 30 days old — expired under 20-day retention, fresh under 90-day
    video = _make_video(db, days_old=30)

    mock_storage = AsyncMock()
    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup

        # Should NOT be deleted with 90-day retention
        deleted = await run_cleanup(db, retention_days=90)
        assert deleted == 0

    # Re-insert since it wasn't deleted
    db.add(video)
    db.commit()

    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        # Should be deleted with 20-day retention
        deleted = await run_cleanup(db, retention_days=20)
        assert deleted == 1


@pytest.mark.asyncio
async def test_cleanup_deletes_multiple_expired_videos(db):
    """All expired videos are deleted in a single run."""
    videos = [_make_video(db, days_old=100 + i) for i in range(5)]

    mock_storage = AsyncMock()
    with patch("app.cleanup.get_storage_backend", return_value=mock_storage):
        from app.cleanup import run_cleanup
        deleted = await run_cleanup(db, retention_days=90)

    assert deleted == 5
    assert mock_storage.delete_video.await_count == 5
    for v in videos:
        assert db.query(Video).filter(Video.id == v.id).first() is None


def test_parse_cleanup_time_valid():
    """_parse_cleanup_time correctly parses 'HH:MM' strings."""
    from app.cleanup import _parse_cleanup_time
    assert _parse_cleanup_time("02:00") == (2, 0)
    assert _parse_cleanup_time("14:30") == (14, 30)
    assert _parse_cleanup_time("00:00") == (0, 0)


def test_parse_cleanup_time_invalid_falls_back():
    """_parse_cleanup_time falls back to 02:00 on bad input."""
    from app.cleanup import _parse_cleanup_time
    assert _parse_cleanup_time("bad") == (2, 0)
    assert _parse_cleanup_time("") == (2, 0)


def test_create_scheduler_returns_scheduler():
    """create_scheduler() returns a configured AsyncIOScheduler."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.cleanup import create_scheduler
    scheduler = create_scheduler()
    assert isinstance(scheduler, AsyncIOScheduler)
    job = scheduler.get_job("storage_cleanup")
    assert job is not None
    assert job.name == "Daily storage cleanup"
