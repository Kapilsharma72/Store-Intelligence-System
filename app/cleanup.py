"""
Scheduled storage cleanup job for the Enhanced Web Dashboard.

Deletes videos older than RETENTION_DAYS (default 90) from storage and the
database, including all associated events and processing jobs.

The scheduler runs daily at CLEANUP_TIME_UTC (default "02:00" UTC) using
APScheduler.  The cleanup logic is also exposed as `run_cleanup(db,
retention_days)` so it can be called directly in tests or admin scripts.

Requirements: 19.1, 19.2, 19.3, 19.4
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Event as EventModel
from app.video_storage import get_storage_backend
from app.videos import ProcessingJob, Video

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", "90"))
CLEANUP_TIME_UTC: str = os.getenv("CLEANUP_TIME_UTC", "02:00")

# ---------------------------------------------------------------------------
# Core cleanup logic
# ---------------------------------------------------------------------------


async def run_cleanup(db: Session, retention_days: int = RETENTION_DAYS) -> int:
    """Delete videos older than *retention_days* from storage and the database.

    For each expired video the function:
    1. Deletes the video file via the configured storage backend.
    2. Deletes all associated ``Event`` rows from PostgreSQL.
    3. Deletes all associated ``ProcessingJob`` rows.
    4. Deletes the ``Video`` row itself.
    5. Logs the deletion with video_id, filename, and deletion timestamp.

    Returns the number of videos deleted.

    Requirements: 19.1, 19.2, 19.4
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    expired_videos = (
        db.query(Video).filter(Video.upload_timestamp < cutoff).all()
    )

    if not expired_videos:
        logger.info("cleanup_no_expired_videos", retention_days=retention_days, cutoff=cutoff.isoformat())
        return 0

    storage = get_storage_backend()
    deleted_count = 0

    for video in expired_videos:
        deletion_ts = datetime.now(timezone.utc).isoformat()
        try:
            # 1. Delete file from storage
            await storage.delete_video(video.id, video.filepath)
        except Exception as exc:
            logger.warning(
                "cleanup_file_delete_failed",
                video_id=video.id,
                filename=video.filename,
                filepath=video.filepath,
                error=str(exc),
            )
            # Continue with DB cleanup even if file deletion fails

        # 2. Delete associated events
        db.query(EventModel).filter(
            EventModel.metadata_["video_id"].as_string() == video.id
        ).delete(synchronize_session=False)

        # 3. Delete associated processing jobs
        db.query(ProcessingJob).filter(
            ProcessingJob.video_id == video.id
        ).delete(synchronize_session=False)

        # 4. Delete the video record
        db.delete(video)
        db.commit()

        # 5. Audit log
        logger.info(
            "cleanup_video_deleted",
            video_id=video.id,
            filename=video.filename,
            deletion_timestamp=deletion_ts,
        )
        deleted_count += 1

    logger.info(
        "cleanup_complete",
        deleted_count=deleted_count,
        retention_days=retention_days,
        cutoff=cutoff.isoformat(),
    )
    return deleted_count


# ---------------------------------------------------------------------------
# Scheduled job wrapper
# ---------------------------------------------------------------------------


async def _scheduled_cleanup() -> None:
    """APScheduler entry point: opens a DB session and runs cleanup."""
    db: Session = SessionLocal()
    try:
        await run_cleanup(db, RETENTION_DAYS)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------


def _parse_cleanup_time(time_str: str):
    """Parse 'HH:MM' into (hour, minute) integers."""
    try:
        hour_str, minute_str = time_str.strip().split(":")
        return int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        logger.warning(
            "cleanup_invalid_time_format",
            value=time_str,
            fallback="02:00",
        )
        return 2, 0


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance.

    The scheduler is *not* started here; call ``scheduler.start()`` after
    the FastAPI application has started.

    Requirements: 19.3
    """
    hour, minute = _parse_cleanup_time(CLEANUP_TIME_UTC)
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _scheduled_cleanup,
        trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        id="storage_cleanup",
        name="Daily storage cleanup",
        replace_existing=True,
    )
    logger.info(
        "cleanup_scheduler_configured",
        hour=hour,
        minute=minute,
        retention_days=RETENTION_DAYS,
    )
    return scheduler
