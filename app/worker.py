"""
Background worker process for asynchronous video processing.

Polls the Redis job queue, runs the detection pipeline on dequeued videos,
publishes frame-level progress to Redis pub/sub, and persists events to the
database on completion.

Features:
  - Polls Redis queue via dequeue_job()
  - Updates job/video status throughout the lifecycle
  - Publishes progress to Redis pub/sub channel `progress:{video_id}`
  - Throttles progress updates to max 2/second
  - Checks cancellation flag `cancel:{video_id}` per frame
  - Retries up to MAX_RETRIES times with exponential backoff on error
  - Supports VFR videos via timestamp-based frame position (CAP_PROP_POS_MSEC)
  - Spawns up to MAX_WORKERS concurrent worker processes

Requirements: 4.3, 4.4, 4.5, 24.1, 24.2, 27.5, 28.4
"""

import asyncio
import json
import multiprocessing
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.database import SessionLocal
from app.job_queue import dequeue_job, get_job_status, set_job_status
from app.redis_client import get_redis, publish
from pipeline.detect import detect_persons
from pipeline.emit import EventEmitter, make_visitor_token
from pipeline.tracker import ByteTracker

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
MAX_WORKERS = 3

# How many frames between progress publishes
PROGRESS_FRAME_INTERVAL = 30

# Minimum seconds between progress publishes (throttle to max 2/second)
PROGRESS_MIN_INTERVAL = 0.5

# Seconds to sleep when the queue is empty before polling again
POLL_INTERVAL = 1.0

# Batch size for event ingestion
EVENT_BATCH_SIZE = 500

# API base URL for event ingestion (fallback to direct DB insert if unavailable)
API_URL = os.getenv("API_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db():
    """Return a new SQLAlchemy session (caller is responsible for closing)."""
    return SessionLocal()


def _update_video_status(video_id: str, new_status: str, db) -> None:
    """Update the Video.status column in the database."""
    from app.videos import Video

    video = db.query(Video).filter(Video.id == video_id).first()
    if video is not None:
        video.status = new_status
        db.commit()
    else:
        logger.warning("video_not_found_for_status_update", video_id=video_id, new_status=new_status)


def _persist_events_to_db(events: list, db) -> None:
    """
    Directly insert a batch of EmittedEvent objects into the database using
    SQLAlchemy (avoids an HTTP round-trip to the ingestion endpoint).

    Requirements: 4.5
    """
    from app.models import Event as EventModel
    from sqlalchemy.exc import IntegrityError

    for event in events:
        try:
            with db.begin_nested():
                db_event = EventModel(
                    event_id=event["event_id"],
                    store_id=event["store_id"],
                    camera_id=event["camera_id"],
                    visitor_id=event["visitor_id"],
                    event_type=event["event_type"],
                    timestamp=event["timestamp"],
                    zone_id=event.get("zone_id"),
                    dwell_ms=event.get("dwell_ms"),
                    is_staff=event.get("is_staff", False),
                    confidence=event.get("confidence", 0.9),
                    metadata_=event.get("metadata"),
                )
                db.add(db_event)
        except IntegrityError:
            # Duplicate event_id — idempotent, skip silently
            pass
        except Exception as exc:
            logger.error("event_persist_failed", event_id=event.get("event_id"), error=str(exc))

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("event_batch_commit_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Core job processor
# ---------------------------------------------------------------------------


async def process_video_job(job_id: str, video_id: str) -> None:
    """
    Main job processing coroutine.

    1. Marks the job and video as "processing".
    2. Opens the video file with OpenCV.
    3. Iterates frames, running detection + tracking.
    4. Publishes progress to Redis pub/sub every PROGRESS_FRAME_INTERVAL frames,
       throttled to at most 2 updates/second.
    5. Checks the Redis cancellation flag `cancel:{video_id}` each frame.
    6. On completion, persists all events to the DB and marks the job "completed".
    7. On error, retries up to MAX_RETRIES times with exponential backoff;
       marks the job "failed" after exhausting retries.

    Requirements: 4.3, 4.4, 4.5, 24.1, 24.2, 27.5, 28.4
    """
    import cv2

    db = _get_db()
    retry_count = 0

    # Retrieve current retry_count from DB if this is a re-attempt
    from app.videos import ProcessingJob

    job_row = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if job_row is not None:
        retry_count = job_row.retry_count or 0

    while True:
        try:
            # ------------------------------------------------------------------
            # 1. Mark job + video as "processing"
            # ------------------------------------------------------------------
            await set_job_status(job_id, "processing", db)
            _update_video_status(video_id, "processing", db)

            job_start_ts = datetime.now(timezone.utc).isoformat()
            processing_start_wall = time.monotonic()

            # Resolve store_config for the start log (req 25.2)
            from app.videos import Video as _Video
            _video_row_for_log = db.query(_Video).filter(_Video.id == video_id).first()
            _store_config_for_log = _video_row_for_log.store_config if _video_row_for_log else None

            logger.info(
                "job_processing_started",
                job_id=job_id,
                video_id=video_id,
                store_config=_store_config_for_log,
                start_timestamp=job_start_ts,
                retry=retry_count,
            )

            # ------------------------------------------------------------------
            # 2. Resolve video file path from DB
            # ------------------------------------------------------------------
            from app.videos import Video

            _db_query_start = time.monotonic()
            video_row = db.query(Video).filter(Video.id == video_id).first()
            _db_query_ms = round((time.monotonic() - _db_query_start) * 1000, 2)
            logger.debug("db_query_duration", query="fetch_video", video_id=video_id, duration_ms=_db_query_ms)

            if video_row is None:
                raise ValueError(f"Video '{video_id}' not found in database")

            video_path = video_row.filepath

            # ------------------------------------------------------------------
            # 3. Open video with OpenCV
            # ------------------------------------------------------------------
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise RuntimeError(f"Cannot open video file: {video_path}")

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

            logger.info(
                "video_opened",
                video_id=video_id,
                path=video_path,
                total_frames=total_frames,
                fps=fps,
            )

            # Update total_frames in the job row
            await set_job_status(job_id, "processing", db, total_frames=total_frames)

            # ------------------------------------------------------------------
            # 4. Initialise pipeline components
            # ------------------------------------------------------------------
            store_id = video_row.store_config or os.path.splitext(os.path.basename(video_path))[0]
            camera_id = video_row.store_config or "CAM_1"
            emitter = EventEmitter()
            tracker = ByteTracker()

            # ------------------------------------------------------------------
            # 5. Frame loop
            # ------------------------------------------------------------------
            redis = get_redis()
            frame_number = 0
            event_batch: list = []
            last_progress_time = 0.0
            processing_start = time.monotonic()

            while True:
                # Check cancellation flag before reading each frame
                cancel_flag = await redis.get(f"cancel:{video_id}")
                if cancel_flag:
                    logger.info("job_cancelled", job_id=job_id, video_id=video_id, frame=frame_number)
                    cap.release()
                    # Persist any buffered events before stopping (Requirement 5.3)
                    if event_batch:
                        _persist_events_to_db(event_batch, db)
                        event_batch = []
                    # Update job status with frame count so status endpoint can report it (Requirement 5.4)
                    await set_job_status(
                        job_id,
                        "cancelled",
                        db,
                        current_frame=frame_number,
                        total_frames=total_frames,
                    )
                    _update_video_status(video_id, "cancelled", db)
                    return

                ret, frame = cap.read()
                if not ret:
                    break

                frame_number += 1

                # VFR support: get timestamp-based position in milliseconds
                timestamp_ms = cap.get(cv2.CAP_PROP_POS_MSEC)  # noqa: F841 — available for downstream use

                # ------------------------------------------------------------------
                # 6. Detection + tracking
                # ------------------------------------------------------------------
                detections = detect_persons(frame)
                tracked = tracker.update_tracks(detections)

                # ------------------------------------------------------------------
                # 7. Emit events for active tracks
                # ------------------------------------------------------------------
                for tp in tracked:
                    if not tp.is_lost:
                        visitor_id = make_visitor_token(store_id, tp.track_id, "session_0")
                        event = emitter.emit_event(
                            event_type="ZONE_ENTER",
                            visitor_id=visitor_id,
                            store_id=store_id,
                            camera_id=camera_id,
                            zone_id=None,
                            video_id=video_id,
                            frame_number=frame_number,
                            timestamp_ms=timestamp_ms,
                        )
                        event_batch.append({
                            "event_id": event.event_id,
                            "event_type": event.event_type,
                            "visitor_id": event.visitor_id,
                            "store_id": event.store_id,
                            "camera_id": event.camera_id,
                            "zone_id": event.zone_id,
                            "timestamp": event.timestamp,
                            "is_staff": False,
                            "confidence": 0.9,
                            "metadata": event.metadata,
                        })

                # Flush event batch when it reaches the batch size limit
                if len(event_batch) >= EVENT_BATCH_SIZE:
                    _persist_events_to_db(event_batch, db)
                    event_batch = []

                # ------------------------------------------------------------------
                # 8. Progress publishing (every PROGRESS_FRAME_INTERVAL frames,
                #    throttled to max 2 updates/second)
                # ------------------------------------------------------------------
                if frame_number % PROGRESS_FRAME_INTERVAL == 0:
                    now = time.monotonic()
                    if now - last_progress_time >= PROGRESS_MIN_INTERVAL:
                        last_progress_time = now

                        percentage = (
                            round(frame_number / total_frames * 100, 1)
                            if total_frames > 0
                            else 0.0
                        )

                        elapsed = now - processing_start
                        if frame_number > 0 and total_frames > 0:
                            frames_remaining = total_frames - frame_number
                            fps_actual = frame_number / elapsed if elapsed > 0 else fps
                            eta_seconds = round(frames_remaining / fps_actual, 1)
                        else:
                            eta_seconds = None

                        progress_payload = json.dumps({
                            "current_frame": frame_number,
                            "total_frames": total_frames,
                            "percentage_complete": percentage,
                            "estimated_time_remaining_seconds": eta_seconds,
                        })

                        await publish(f"progress:{video_id}", progress_payload)

                        # Also update the DB job row with current progress
                        await set_job_status(
                            job_id,
                            "processing",
                            db,
                            current_frame=frame_number,
                            total_frames=total_frames,
                        )

                        logger.debug(
                            "progress_published",
                            video_id=video_id,
                            frame=frame_number,
                            total=total_frames,
                            pct=percentage,
                        )

            cap.release()

            # ------------------------------------------------------------------
            # 9. Persist remaining events
            # ------------------------------------------------------------------
            if event_batch:
                _persist_events_to_db(event_batch, db)
                event_batch = []

            # ------------------------------------------------------------------
            # 10. Store analytics summary (frame count, completion time)
            # ------------------------------------------------------------------
            completed_at = datetime.now(timezone.utc).isoformat()
            analytics_summary = json.dumps({
                "video_id": video_id,
                "total_frames_processed": frame_number,
                "completed_at": completed_at,
            })
            await redis.set(f"analytics:{video_id}", analytics_summary, ex=86400)

            # ------------------------------------------------------------------
            # 11. Mark job + video as "completed"
            # ------------------------------------------------------------------
            await set_job_status(
                job_id,
                "completed",
                db,
                current_frame=frame_number,
                total_frames=total_frames,
            )
            _update_video_status(video_id, "completed", db)

            # Publish final 100% progress
            final_progress = json.dumps({
                "current_frame": frame_number,
                "total_frames": total_frames,
                "percentage_complete": 100.0,
                "estimated_time_remaining_seconds": 0,
            })
            await publish(f"progress:{video_id}", final_progress)

            logger.info(
                "job_completed",
                job_id=job_id,
                video_id=video_id,
                frames_processed=frame_number,
                duration_seconds=round(time.monotonic() - processing_start_wall, 2),
                frame_rate=round(frame_number / (time.monotonic() - processing_start_wall), 2) if (time.monotonic() - processing_start_wall) > 0 else 0.0,
            )
            return  # success — exit the retry loop

        except Exception as exc:
            _tb = traceback.format_exc()
            _trace_id = structlog.contextvars.get_contextvars().get("trace_id", "")
            logger.error(
                "job_processing_error",
                job_id=job_id,
                video_id=video_id,
                retry=retry_count,
                error=str(exc),
                error_type=type(exc).__name__,
                stack_trace=_tb,
                trace_id=_trace_id,
            )

            retry_count += 1

            # Update retry_count in DB
            job_row = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job_row is not None:
                job_row.retry_count = retry_count
                db.commit()

            if retry_count < MAX_RETRIES:
                backoff = 2 ** retry_count  # exponential backoff: 2, 4, 8 seconds
                logger.info(
                    "job_retry_scheduled",
                    job_id=job_id,
                    video_id=video_id,
                    retry=retry_count,
                    backoff_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                # Loop back to retry
            else:
                # Exhausted retries — mark as failed
                error_message = str(exc)
                await set_job_status(job_id, "failed", db, error_message=error_message)
                _update_video_status(video_id, "failed", db)
                logger.error(
                    "job_failed_permanently",
                    job_id=job_id,
                    video_id=video_id,
                    error=error_message,
                    error_type=type(exc).__name__,
                    stack_trace=_tb,
                    trace_id=_trace_id,
                )
                return
        finally:
            # DB session is kept open across retries; closed after the loop exits
            pass

    # Close the session after the retry loop exits (success or permanent failure)
    db.close()


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------


async def worker_loop() -> None:
    """
    Infinite loop that polls the Redis job queue and processes jobs one at a time.

    Requirements: 4.3, 27.5
    """
    logger.info("worker_loop_started", pid=os.getpid())

    while True:
        try:
            job_id = await dequeue_job()

            if job_id is None:
                # Queue is empty — wait before polling again
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Retrieve video_id from the Redis job hash
            job_data = await get_job_status(job_id)
            if job_data is None:
                logger.warning("job_data_not_found", job_id=job_id)
                continue

            video_id = job_data.get("video_id")
            if not video_id:
                logger.warning("job_missing_video_id", job_id=job_id, data=job_data)
                continue

            logger.info("job_picked_up", job_id=job_id, video_id=video_id, pid=os.getpid())
            await process_video_job(job_id, video_id)

        except asyncio.CancelledError:
            logger.info("worker_loop_cancelled", pid=os.getpid())
            break
        except Exception as exc:
            # Unexpected error in the loop itself — log and keep running
            logger.error("worker_loop_error", error=str(exc), pid=os.getpid())
            await asyncio.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Process entry point
# ---------------------------------------------------------------------------


def _run_worker_process() -> None:
    """Entry point for each worker subprocess — runs the async worker loop."""
    asyncio.run(worker_loop())


# ---------------------------------------------------------------------------
# Multi-process launcher
# ---------------------------------------------------------------------------


def run_workers() -> None:
    """
    Spawn up to MAX_WORKERS worker processes using multiprocessing.Process.

    Each process runs its own asyncio event loop with worker_loop().

    Requirements: 27.5, 28.4
    """
    logger.info("starting_workers", count=MAX_WORKERS)

    processes: list[multiprocessing.Process] = []

    for i in range(MAX_WORKERS):
        p = multiprocessing.Process(
            target=_run_worker_process,
            name=f"video-worker-{i}",
            daemon=True,
        )
        p.start()
        processes.append(p)
        logger.info("worker_process_started", worker_index=i, pid=p.pid)

    # Wait for all worker processes (they run indefinitely until interrupted)
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        logger.info("shutdown_signal_received")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join(timeout=5)
        logger.info("all_workers_stopped")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_workers()
