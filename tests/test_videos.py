"""
Unit tests for app/videos.py — video management endpoints.

Tests cover:
  - POST /api/v1/videos/upload
  - GET  /api/v1/videos
  - GET  /api/v1/videos/{video_id}
  - DELETE /api/v1/videos/{video_id}
  - GET  /api/v1/videos/{video_id}/status

Requirements: 1.3, 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 17.4
"""

import io
import uuid
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import UserContext, get_current_user
from app.database import Base, get_db
from app.main import app
from app.videos import ProcessingJob, Video

# ---------------------------------------------------------------------------
# In-memory test database
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"

_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _make_client(username: str = "user", role: str = "user") -> TestClient:
    """Return a TestClient with auth and DB overrides applied."""
    user_ctx = UserContext(username=username, role=role)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: user_ctx
    return TestClient(app)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    yield _make_client()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def admin_client() -> Generator[TestClient, None, None]:
    yield _make_client(username="admin", role="admin")
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _seed_video(db, video_id=None, uploaded_by="user", status="pending") -> Video:
    """Insert a Video row directly into the test DB."""
    v = Video(
        id=video_id or str(uuid.uuid4()),
        filename="test.mp4",
        filepath=f"data/videos/{video_id or 'x'}/test.mp4",
        duration_seconds=10.0,
        resolution="1280x720",
        codec="h264",
        file_size_bytes=1024,
        store_config=None,
        status=status,
        upload_timestamp=datetime.now(timezone.utc),
        uploaded_by=uploaded_by,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def _seed_job(db, video_id, status="processing", current_frame=50, total_frames=100) -> ProcessingJob:
    """Insert a ProcessingJob row directly into the test DB."""
    j = ProcessingJob(
        id=str(uuid.uuid4()),
        video_id=video_id,
        status=status,
        current_frame=current_frame,
        total_frames=total_frames,
        error_message=None,
    )
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


# ---------------------------------------------------------------------------
# POST /api/v1/videos/upload
# ---------------------------------------------------------------------------


class TestUploadVideo:
    def test_upload_valid_video_returns_201(self, client):
        """A valid video upload should return 201 with video metadata."""
        fake_metadata = {
            "duration": 5.0,
            "width": 1280,
            "height": 720,
            "codec": "h264",
            "frame_rate": 30.0,
            "format": "mp4",
        }
        with (
            patch("app.videos.validate_video", return_value=fake_metadata),
            patch(
                "app.videos.get_storage_backend",
                return_value=MagicMock(
                    save_video=AsyncMock(return_value="data/videos/vid123/test.mp4")
                ),
            ),
        ):
            response = client.post(
                "/api/v1/videos/upload",
                files={"file": ("test.mp4", b"fake-video-bytes", "video/mp4")},
            )

        assert response.status_code == 201
        body = response.json()
        assert "video_id" in body
        assert body["filename"] == "test.mp4"
        assert body["status"] == "pending"
        assert body["codec"] == "h264"
        assert body["resolution"] == "1280x720"
        assert body["duration_seconds"] == 5.0

    def test_upload_with_store_config(self, client):
        """store_config form field should be persisted."""
        fake_metadata = {
            "duration": 3.0,
            "width": 1920,
            "height": 1080,
            "codec": "h264",
            "frame_rate": 25.0,
            "format": "mp4",
        }
        with (
            patch("app.videos.validate_video", return_value=fake_metadata),
            patch(
                "app.videos.get_storage_backend",
                return_value=MagicMock(
                    save_video=AsyncMock(return_value="data/videos/x/test.mp4")
                ),
            ),
        ):
            response = client.post(
                "/api/v1/videos/upload",
                files={"file": ("test.mp4", b"bytes", "video/mp4")},
                data={"store_config": "STORE_001"},
            )

        assert response.status_code == 201
        assert response.json()["store_config"] == "STORE_001"

    def test_upload_validation_failure_returns_422(self, client):
        """If validate_video raises HTTPException, the upload should fail."""
        from fastapi import HTTPException

        with patch(
            "app.videos.validate_video",
            side_effect=HTTPException(
                status_code=422,
                detail={"error": "Unsupported codec", "field": "codec", "value": "wmv"},
            ),
        ):
            response = client.post(
                "/api/v1/videos/upload",
                files={"file": ("bad.wmv", b"bad-bytes", "video/x-ms-wmv")},
            )

        assert response.status_code == 422

    def test_upload_requires_auth(self):
        """Without auth override, upload should return 401."""
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides[get_db] = _override_get_db
        c = TestClient(app)
        response = c.post(
            "/api/v1/videos/upload",
            files={"file": ("test.mp4", b"bytes", "video/mp4")},
        )
        assert response.status_code == 401
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /api/v1/videos
# ---------------------------------------------------------------------------


class TestListVideos:
    def test_list_returns_own_videos(self, client, db):
        """User should only see their own videos."""
        _seed_video(db, uploaded_by="user")
        _seed_video(db, uploaded_by="other_user")

        response = client.get("/api/v1/videos")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["filename"] == "test.mp4"

    def test_admin_sees_all_videos(self, admin_client, db):
        """Admin should see all videos regardless of owner."""
        _seed_video(db, uploaded_by="user")
        _seed_video(db, uploaded_by="other_user")

        response = admin_client.get("/api/v1/videos")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_list_pagination(self, client, db):
        """Pagination params should be respected."""
        for _ in range(5):
            _seed_video(db, uploaded_by="user")

        response = client.get("/api/v1/videos?page=1&page_size=2")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["page"] == 1
        assert body["page_size"] == 2

    def test_list_includes_processing_status(self, client, db):
        """Each item should include the latest processing job status."""
        v = _seed_video(db, uploaded_by="user")
        _seed_job(db, v.id, status="processing")

        response = client.get("/api/v1/videos")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["processing_status"] == "processing"

    def test_list_empty(self, client, db):
        """Empty list should return total=0."""
        response = client.get("/api/v1/videos")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}
# ---------------------------------------------------------------------------


class TestGetVideo:
    def test_get_own_video(self, client, db):
        """Owner can retrieve their video details."""
        v = _seed_video(db, uploaded_by="user")
        response = client.get(f"/api/v1/videos/{v.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["video_id"] == v.id
        assert body["filename"] == "test.mp4"

    def test_get_video_with_processing_job(self, client, db):
        """Response should include processing job summary when a job exists."""
        v = _seed_video(db, uploaded_by="user")
        j = _seed_job(db, v.id, status="completed", current_frame=100, total_frames=100)

        response = client.get(f"/api/v1/videos/{v.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["processing"]["status"] == "completed"
        assert body["processing"]["job_id"] == j.id

    def test_get_video_not_found_returns_404(self, client):
        """Non-existent video_id should return 404."""
        response = client.get(f"/api/v1/videos/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_get_other_users_video_returns_403(self, client, db):
        """Accessing another user's video should return 403."""
        v = _seed_video(db, uploaded_by="other_user")
        response = client.get(f"/api/v1/videos/{v.id}")
        assert response.status_code == 403

    def test_admin_can_get_any_video(self, admin_client, db):
        """Admin can access any video regardless of owner."""
        v = _seed_video(db, uploaded_by="some_user")
        response = admin_client.get(f"/api/v1/videos/{v.id}")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /api/v1/videos/{video_id}
# ---------------------------------------------------------------------------


class TestDeleteVideo:
    def test_delete_own_video_returns_204(self, client, db):
        """Owner can delete their video."""
        v = _seed_video(db, uploaded_by="user")
        with patch(
            "app.videos.get_storage_backend",
            return_value=MagicMock(delete_video=AsyncMock()),
        ):
            response = client.delete(f"/api/v1/videos/{v.id}")
        assert response.status_code == 204

    def test_delete_removes_db_row(self, client, db):
        """After deletion, the video row should not exist in the DB."""
        v = _seed_video(db, uploaded_by="user")
        vid_id = v.id
        with patch(
            "app.videos.get_storage_backend",
            return_value=MagicMock(delete_video=AsyncMock()),
        ):
            client.delete(f"/api/v1/videos/{vid_id}")

        remaining = db.query(Video).filter(Video.id == vid_id).first()
        assert remaining is None

    def test_delete_removes_processing_jobs(self, client, db):
        """Deleting a video should also remove its processing jobs."""
        v = _seed_video(db, uploaded_by="user")
        _seed_job(db, v.id)
        with patch(
            "app.videos.get_storage_backend",
            return_value=MagicMock(delete_video=AsyncMock()),
        ):
            client.delete(f"/api/v1/videos/{v.id}")

        jobs = db.query(ProcessingJob).filter(ProcessingJob.video_id == v.id).all()
        assert jobs == []

    def test_delete_not_found_returns_404(self, client):
        """Deleting a non-existent video should return 404."""
        with patch(
            "app.videos.get_storage_backend",
            return_value=MagicMock(delete_video=AsyncMock()),
        ):
            response = client.delete(f"/api/v1/videos/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_delete_other_users_video_returns_403(self, client, db):
        """Deleting another user's video should return 403."""
        v = _seed_video(db, uploaded_by="other_user")
        with patch(
            "app.videos.get_storage_backend",
            return_value=MagicMock(delete_video=AsyncMock()),
        ):
            response = client.delete(f"/api/v1/videos/{v.id}")
        assert response.status_code == 403

    def test_admin_can_delete_any_video(self, admin_client, db):
        """Admin can delete any video."""
        v = _seed_video(db, uploaded_by="some_user")
        with patch(
            "app.videos.get_storage_backend",
            return_value=MagicMock(delete_video=AsyncMock()),
        ):
            response = admin_client.delete(f"/api/v1/videos/{v.id}")
        assert response.status_code == 204


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/status
# ---------------------------------------------------------------------------


class TestGetVideoStatus:
    def test_status_no_job(self, client, db):
        """Status endpoint returns video status with no progress when no job exists."""
        v = _seed_video(db, uploaded_by="user", status="pending")
        response = client.get(f"/api/v1/videos/{v.id}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["video_id"] == v.id
        assert body["status"] == "pending"
        assert body["progress_pct"] is None

    def test_status_with_job_progress(self, client, db):
        """Status endpoint computes progress_pct from current/total frames."""
        v = _seed_video(db, uploaded_by="user", status="processing")
        _seed_job(db, v.id, status="processing", current_frame=25, total_frames=100)

        response = client.get(f"/api/v1/videos/{v.id}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["progress_pct"] == 25.0
        assert body["current_frame"] == 25
        assert body["total_frames"] == 100

    def test_status_completed(self, client, db):
        """Completed job should show 100% progress."""
        v = _seed_video(db, uploaded_by="user", status="completed")
        _seed_job(db, v.id, status="completed", current_frame=100, total_frames=100)

        response = client.get(f"/api/v1/videos/{v.id}/status")
        assert response.status_code == 200
        assert response.json()["progress_pct"] == 100.0

    def test_status_not_found_returns_404(self, client):
        """Non-existent video_id should return 404."""
        response = client.get(f"/api/v1/videos/{uuid.uuid4()}/status")
        assert response.status_code == 404

    def test_status_other_users_video_returns_403(self, client, db):
        """Accessing another user's video status should return 403."""
        v = _seed_video(db, uploaded_by="other_user")
        response = client.get(f"/api/v1/videos/{v.id}/status")
        assert response.status_code == 403

    def test_status_with_error_message(self, client, db):
        """Failed job should expose error_message in status response."""
        v = _seed_video(db, uploaded_by="user", status="failed")
        j = ProcessingJob(
            id=str(uuid.uuid4()),
            video_id=v.id,
            status="failed",
            current_frame=None,
            total_frames=None,
            error_message="Pipeline crashed",
        )
        db.add(j)
        db.commit()

        response = client.get(f"/api/v1/videos/{v.id}/status")
        assert response.status_code == 200
        assert response.json()["error_message"] == "Pipeline crashed"


# ---------------------------------------------------------------------------
# POST /api/v1/videos/{video_id}/process
# ---------------------------------------------------------------------------


class TestProcessVideo:
    def test_process_pending_video_returns_202(self, client, db):
        """Enqueuing a pending video should return 202 with job_id."""
        v = _seed_video(db, uploaded_by="user", status="pending")
        with patch("app.job_queue.enqueue_job", new_callable=AsyncMock, return_value="job-abc"):
            response = client.post(f"/api/v1/videos/{v.id}/process")
        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == "job-abc"
        assert body["video_id"] == v.id
        assert body["status"] == "pending"

    def test_process_updates_video_status_to_pending(self, client, db):
        """After enqueuing, the video status in DB should be 'pending'."""
        v = _seed_video(db, uploaded_by="user", status="pending")
        with patch("app.job_queue.enqueue_job", new_callable=AsyncMock, return_value="job-xyz"):
            client.post(f"/api/v1/videos/{v.id}/process")
        db.refresh(v)
        assert v.status == "pending"

    def test_process_already_processing_returns_409(self, client, db):
        """A video already being processed should return 409 Conflict."""
        v = _seed_video(db, uploaded_by="user", status="processing")
        response = client.post(f"/api/v1/videos/{v.id}/process")
        assert response.status_code == 409
        assert "already being processed" in response.json()["detail"]

    def test_process_cancelled_video_resets_and_enqueues(self, client, db):
        """A cancelled video should be reset to pending and old jobs deleted (Req 5.5)."""
        v = _seed_video(db, uploaded_by="user", status="cancelled")
        old_job = _seed_job(db, v.id, status="cancelled")
        with patch("app.job_queue.enqueue_job", new_callable=AsyncMock, return_value="new-job"), \
             patch("app.videos.cache_invalidate_pattern", new_callable=AsyncMock):
            response = client.post(f"/api/v1/videos/{v.id}/process")
        assert response.status_code == 202
        assert response.json()["job_id"] == "new-job"
        # Old job should be deleted
        remaining = db.query(ProcessingJob).filter(ProcessingJob.id == old_job.id).first()
        assert remaining is None

    def test_process_completed_video_allowed(self, client, db):
        """Re-processing a completed video should be allowed (returns 202)."""
        v = _seed_video(db, uploaded_by="user", status="completed")
        with patch("app.job_queue.enqueue_job", new_callable=AsyncMock, return_value="re-job"):
            response = client.post(f"/api/v1/videos/{v.id}/process")
        assert response.status_code == 202

    def test_process_not_found_returns_404(self, client):
        """Non-existent video_id should return 404."""
        response = client.post(f"/api/v1/videos/{uuid.uuid4()}/process")
        assert response.status_code == 404

    def test_process_other_users_video_returns_403(self, client, db):
        """Processing another user's video should return 403."""
        v = _seed_video(db, uploaded_by="other_user", status="pending")
        response = client.post(f"/api/v1/videos/{v.id}/process")
        assert response.status_code == 403

    def test_process_queue_full_propagates_503(self, client, db):
        """If enqueue_job raises HTTP 503, the endpoint should propagate it."""
        from fastapi import HTTPException as FastAPIHTTPException

        v = _seed_video(db, uploaded_by="user", status="pending")
        with patch(
            "app.job_queue.enqueue_job",
            new_callable=AsyncMock,
            side_effect=FastAPIHTTPException(status_code=503, detail="Queue is full"),
        ):
            response = client.post(f"/api/v1/videos/{v.id}/process")
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/v1/videos/{video_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelVideo:
    def test_cancel_video_returns_200(self, client, db):
        """Cancelling a video should return 200 with cancelled status."""
        v = _seed_video(db, uploaded_by="user", status="processing")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("app.videos.get_redis", return_value=mock_redis), \
             patch("app.videos.cache_invalidate_pattern", new_callable=AsyncMock):
            response = client.post(f"/api/v1/videos/{v.id}/cancel")
        assert response.status_code == 200
        body = response.json()
        assert body["video_id"] == v.id
        assert body["status"] == "cancelled"

    def test_cancel_sets_redis_flag(self, client, db):
        """Cancelling should set the cancel:{video_id} key in Redis."""
        v = _seed_video(db, uploaded_by="user", status="processing")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("app.videos.get_redis", return_value=mock_redis), \
             patch("app.videos.cache_invalidate_pattern", new_callable=AsyncMock):
            client.post(f"/api/v1/videos/{v.id}/cancel")
        mock_redis.set.assert_called_once_with(f"cancel:{v.id}", "1", ex=3600)

    def test_cancel_updates_video_status_in_db(self, client, db):
        """Cancelling should update the video status to 'cancelled' in DB."""
        v = _seed_video(db, uploaded_by="user", status="processing")
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("app.videos.get_redis", return_value=mock_redis), \
             patch("app.videos.cache_invalidate_pattern", new_callable=AsyncMock):
            client.post(f"/api/v1/videos/{v.id}/cancel")
        db.refresh(v)
        assert v.status == "cancelled"

    def test_cancel_not_found_returns_404(self, client):
        """Cancelling a non-existent video should return 404."""
        response = client.post(f"/api/v1/videos/{uuid.uuid4()}/cancel")
        assert response.status_code == 404

    def test_cancel_other_users_video_returns_403(self, client, db):
        """Cancelling another user's video should return 403."""
        v = _seed_video(db, uploaded_by="other_user", status="processing")
        response = client.post(f"/api/v1/videos/{v.id}/cancel")
        assert response.status_code == 403
