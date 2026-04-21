"""
Video management router for the Enhanced Web Dashboard.

Provides:
  - POST /api/v1/videos/upload              — validate, store, and register a video
  - GET  /api/v1/videos                     — paginated list of videos owned by current user
  - GET  /api/v1/videos/{video_id}          — detailed metadata + latest processing status
  - DELETE /api/v1/videos/{video_id}        — delete file, events, processing jobs, and DB row
  - GET  /api/v1/videos/{video_id}/status   — current status, progress %, error message
  - POST /api/v1/videos/{video_id}/process  — enqueue a processing job, returns HTTP 202
  - POST /api/v1/videos/{video_id}/cancel   — cancel an in-progress processing job

All endpoints require a valid Bearer token (get_current_user dependency).
Ownership is enforced: only the uploader or an admin may access/modify a video.

Requirements: 1.3, 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 5.1, 5.5, 17.4
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Annotated, List, Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user
from app.database import Base, get_db
from app.redis_client import cache_invalidate_pattern, get_redis
from app.video_storage import get_storage_backend
from app.video_validation import validate_video

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------


class Video(Base):
    """ORM model for the `videos` table (created in migration 0002)."""

    __tablename__ = "videos"

    id = Column(String(36), primary_key=True)
    filename = Column(String(255), nullable=False)
    filepath = Column(String(1024), nullable=False)
    duration_seconds = Column(Float, nullable=True)
    resolution = Column(String(20), nullable=True)
    codec = Column(String(50), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    store_config = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    upload_timestamp = Column(DateTime(timezone=True), nullable=False)
    uploaded_by = Column(String(100), nullable=True)


class ProcessingJob(Base):
    """ORM model for the `processing_jobs` table (created in migration 0002)."""

    __tablename__ = "processing_jobs"

    id = Column(String(36), primary_key=True)
    video_id = Column(String(36), ForeignKey("videos.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    current_frame = Column(Integer, nullable=True)
    total_frames = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class VideoResponse(BaseModel):
    video_id: str
    filename: str
    duration_seconds: Optional[float]
    resolution: Optional[str]
    codec: Optional[str]
    file_size_bytes: Optional[int]
    store_config: Optional[str]
    status: str
    upload_timestamp: datetime

    model_config = {"from_attributes": True}


class ProcessingJobSummary(BaseModel):
    job_id: Optional[str] = None
    status: Optional[str] = None
    current_frame: Optional[int] = None
    total_frames: Optional[int] = None
    error_message: Optional[str] = None


class VideoDetailResponse(VideoResponse):
    processing: Optional[ProcessingJobSummary] = None


class VideoListItem(BaseModel):
    video_id: str
    filename: str
    duration_seconds: Optional[float]
    resolution: Optional[str]
    status: str
    upload_timestamp: datetime
    processing_status: Optional[str] = None

    model_config = {"from_attributes": True}


class VideoListResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: List[VideoListItem]


class VideoStatusResponse(BaseModel):
    video_id: str
    status: str
    progress_pct: Optional[float] = None
    current_frame: Optional[int] = None
    total_frames: Optional[int] = None
    error_message: Optional[str] = None


class ProcessResponse(BaseModel):
    job_id: str
    video_id: str
    status: str = "pending"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_ownership(video: Video, current_user: Optional[UserContext]) -> None:
    """Raise HTTP 403 if the current user does not own the video and is not admin.
    
    If current_user is None (no authentication), access is allowed.
    """
    if current_user is None:
        # No authentication - allow access
        return
    
    if video.uploaded_by != current_user.username and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this video",
        )


def _get_video_or_404(video_id: str, db: Session) -> Video:
    """Fetch a Video row by ID or raise HTTP 404."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video '{video_id}' not found",
        )
    return video


def _latest_job(video_id: str, db: Session) -> Optional[ProcessingJob]:
    """Return the most recently started processing job for a video, or None."""
    return (
        db.query(ProcessingJob)
        .filter(ProcessingJob.video_id == video_id)
        .order_by(ProcessingJob.started_at.desc().nullslast())
        .first()
    )


def _progress_pct(job: Optional[ProcessingJob]) -> Optional[float]:
    """Compute progress percentage from a processing job, or None."""
    if job is None:
        return None
    if job.total_frames and job.total_frames > 0 and job.current_frame is not None:
        return round(job.current_frame / job.total_frames * 100, 1)
    return None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


# ---------------------------------------------------------------------------
# POST /api/v1/videos/upload
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def upload_video(
    file: UploadFile = File(...),
    store_config: Optional[str] = Form(None),
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> VideoResponse:
    """
    Upload and validate a video file, then persist it to storage and the database.

    Requirements: 1.3, 3.1, 3.2, 17.4
    
    Note: Rate limiting is disabled when Redis is unavailable.
    """
    file_content = await file.read()
    original_filename = file.filename or "upload"
    video_id = str(uuid.uuid4())

    # Write to a temporary file so ffprobe can inspect it
    suffix = os.path.splitext(original_filename)[1] or ".tmp"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_file:
            tmp_file.write(file_content)

        # Validate — raises HTTPException on failure
        metadata = validate_video(file_content, tmp_path)
    finally:
        # Always clean up the temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Persist to permanent storage
    storage = get_storage_backend()
    filepath = await storage.save_video(file_content, video_id, original_filename)

    resolution = f"{metadata['width']}x{metadata['height']}"
    
    # Get username for tracking (use "anonymous" if no auth)
    username = current_user.username if current_user else "anonymous"

    # Insert DB row
    now = datetime.now(timezone.utc)
    video = Video(
        id=video_id,
        filename=original_filename,
        filepath=filepath,
        duration_seconds=metadata.get("duration"),
        resolution=resolution,
        codec=metadata.get("codec"),
        file_size_bytes=len(file_content),
        store_config=store_config,
        status="pending",
        upload_timestamp=now,
        uploaded_by=username,
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    logger.info(
        "video_uploaded",
        video_id=video_id,
        filename=original_filename,
        uploaded_by=username,
        file_size_bytes=len(file_content),
    )

    return VideoResponse(
        video_id=video.id,
        filename=video.filename,
        duration_seconds=video.duration_seconds,
        resolution=video.resolution,
        codec=video.codec,
        file_size_bytes=video.file_size_bytes,
        store_config=video.store_config,
        status=video.status,
        upload_timestamp=video.upload_timestamp,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/videos
# ---------------------------------------------------------------------------


@router.get("", response_model=VideoListResponse)
def list_videos(
    page: int = 1,
    page_size: int = 20,
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> VideoListResponse:
    """
    Return a paginated list of videos owned by the current user.

    Admins see all videos. If no authentication, all videos are shown.
    Each item includes the latest processing job status.

    Requirements: 1.5, 3.2, 17.4
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    query = db.query(Video)
    # Filter by user only if authenticated and not admin
    if current_user and current_user.role != "admin":
        query = query.filter(Video.uploaded_by == current_user.username)

    total = query.count()
    videos = (
        query.order_by(Video.upload_timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items: List[VideoListItem] = []
    for v in videos:
        job = _latest_job(v.id, db)
        items.append(
            VideoListItem(
                video_id=v.id,
                filename=v.filename,
                duration_seconds=v.duration_seconds,
                resolution=v.resolution,
                status=v.status,
                upload_timestamp=v.upload_timestamp,
                processing_status=job.status if job else None,
            )
        )

    return VideoListResponse(page=page, page_size=page_size, total=total, items=items)


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}
# ---------------------------------------------------------------------------


@router.get("/{video_id}", response_model=VideoDetailResponse)
def get_video(
    video_id: str,
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> VideoDetailResponse:
    """
    Return detailed metadata and latest processing job status for a video.

    Requirements: 3.3, 17.4
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    job = _latest_job(video_id, db)
    processing = None
    if job:
        processing = ProcessingJobSummary(
            job_id=job.id,
            status=job.status,
            current_frame=job.current_frame,
            total_frames=job.total_frames,
            error_message=job.error_message,
        )

    return VideoDetailResponse(
        video_id=video.id,
        filename=video.filename,
        duration_seconds=video.duration_seconds,
        resolution=video.resolution,
        codec=video.codec,
        file_size_bytes=video.file_size_bytes,
        store_config=video.store_config,
        status=video.status,
        upload_timestamp=video.upload_timestamp,
        processing=processing,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/videos/{video_id}
# ---------------------------------------------------------------------------


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: str,
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete a video: removes the file from storage, all associated events,
    processing job rows, and the videos DB row.

    Requirements: 3.4, 17.4
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    # Delete file from storage backend
    storage = get_storage_backend()
    try:
        await storage.delete_video(video_id, video.filepath)
    except Exception as exc:
        logger.warning(
            "video_file_delete_failed",
            video_id=video_id,
            filepath=video.filepath,
            error=str(exc),
        )
        # Continue with DB cleanup even if file deletion fails

    # Delete events that reference this video (stored in metadata context)
    # Events store video context in the metadata_ JSON column
    from app.models import Event as EventModel

    events_deleted = (
        db.query(EventModel)
        .filter(EventModel.metadata_["video_id"].as_string() == video_id)
        .delete(synchronize_session=False)
    )

    # Delete processing jobs
    jobs_deleted = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.video_id == video_id)
        .delete(synchronize_session=False)
    )

    # Delete the video row
    db.delete(video)
    db.commit()

    logger.info(
        "video_deleted",
        video_id=video_id,
        filename=video.filename,
        deleted_by=current_user.username if current_user else "anonymous",
        events_deleted=events_deleted,
        jobs_deleted=jobs_deleted,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/status
# ---------------------------------------------------------------------------


@router.get("/{video_id}/status", response_model=VideoStatusResponse)
def get_video_status(
    video_id: str,
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> VideoStatusResponse:
    """
    Return the current processing status, progress percentage, and error message
    for a video.

    Requirements: 3.5, 17.4
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    job = _latest_job(video_id, db)
    pct = _progress_pct(job)

    return VideoStatusResponse(
        video_id=video_id,
        status=video.status,
        progress_pct=pct,
        current_frame=job.current_frame if job else None,
        total_frames=job.total_frames if job else None,
        error_message=job.error_message if job else None,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/videos/{video_id}/process
# ---------------------------------------------------------------------------


@router.post("/{video_id}/process", response_model=ProcessResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_video(
    video_id: str,
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> ProcessResponse:
    """
    Enqueue a processing job for the given video and return HTTP 202.

    - If the video is already "processing", raises HTTP 409 Conflict.
    - If the video was "cancelled", resets it to "pending" and deletes existing
      processing jobs so processing restarts from the beginning (Requirement 5.5).
    - If the video is "completed", allows re-processing.
    - Propagates HTTP 503 from enqueue_job if the queue is full.

    Requirements: 4.1, 5.5
    """
    # Import here to avoid circular import (job_queue imports from videos)
    from app.job_queue import enqueue_job

    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    if video.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video is already being processed",
        )

    if video.status == "cancelled":
        # Restart from beginning: delete existing processing jobs (Requirement 5.5)
        db.query(ProcessingJob).filter(ProcessingJob.video_id == video_id).delete(
            synchronize_session=False
        )
        video.status = "pending"
        db.commit()
        db.refresh(video)
        # Invalidate cached analytics since status changed (Requirement 29.4)
        await cache_invalidate_pattern(f"analytics:{video_id}:*")
        logger.info(
            "video_reprocess_after_cancel",
            video_id=video_id,
            requested_by=current_user.username if current_user else "anonymous",
        )

    # Enqueue the job — raises HTTP 503 if queue is full
    job_id = await enqueue_job(video_id, db)

    # Update video status to "pending" in the DB
    video.status = "pending"
    db.commit()

    logger.info(
        "video_process_enqueued",
        video_id=video_id,
        job_id=job_id,
        requested_by=current_user.username if current_user else "anonymous",
    )

    return ProcessResponse(job_id=job_id, video_id=video_id, status="pending")


# ---------------------------------------------------------------------------
# POST /api/v1/videos/{video_id}/cancel
# ---------------------------------------------------------------------------


@router.post("/{video_id}/cancel")
async def cancel_video(
    video_id: str,
    current_user: Annotated[Optional[UserContext], Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> dict:
    """
    Mark a video's processing job for cancellation.

    Sets a cancellation flag in Redis and updates the video status to "cancelled".

    Requirements: 5.1
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    # Set cancellation flag in Redis (TTL 1 hour)
    redis = get_redis()
    await redis.set(f"cancel:{video_id}", "1", ex=3600)

    # Update video status to "cancelled" in DB
    video.status = "cancelled"
    db.commit()

    # Invalidate all cached analytics for this video (Requirement 29.4)
    await cache_invalidate_pattern(f"analytics:{video_id}:*")

    logger.info(
        "video_cancel_requested",
        video_id=video_id,
        requested_by=current_user.username if current_user else "anonymous",
    )

    return {"video_id": video_id, "status": "cancelled"}
