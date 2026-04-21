"""
Video storage backends for the Enhanced Web Dashboard.

Supports local filesystem and S3 storage, selected via the
STORAGE_BACKEND environment variable ('local' or 's3').
"""

import os
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
LOCAL_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH", "data/videos")

# S3 configuration (only required when STORAGE_BACKEND=s3)
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")

# Presigned URL expiry in seconds (1 hour)
_PRESIGNED_URL_EXPIRY = 3600


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class VideoStorageBackend(ABC):
    """Protocol / abstract base class for video storage backends."""

    @abstractmethod
    async def save_video(
        self, file_content: bytes, video_id: str, filename: str
    ) -> str:
        """Save *file_content* and return the storage path or S3 key."""

    @abstractmethod
    async def delete_video(self, video_id: str, filepath: str) -> None:
        """Delete the video identified by *video_id* at *filepath*."""

    @abstractmethod
    async def get_video_path(self, video_id: str, filepath: str) -> str:
        """Return a local filesystem path or a presigned URL for the video."""


# ---------------------------------------------------------------------------
# Local filesystem backend
# ---------------------------------------------------------------------------


class LocalStorageBackend(VideoStorageBackend):
    """Stores videos on the local filesystem under LOCAL_STORAGE_PATH."""

    def __init__(self, base_path: str = LOCAL_STORAGE_PATH) -> None:
        self.base_path = Path(base_path)

    async def save_video(
        self, file_content: bytes, video_id: str, filename: str
    ) -> str:
        """Save *file_content* to ``{base_path}/{video_id}/{filename}``.

        Creates intermediate directories as needed.
        Returns the relative storage path.
        """
        dest_dir = self.base_path / video_id
        # Run blocking I/O in a thread pool to keep the event loop free
        await asyncio.get_event_loop().run_in_executor(
            None, dest_dir.mkdir, 0o755, True, True
        )

        dest_path = dest_dir / filename

        def _write() -> None:
            dest_path.write_bytes(file_content)

        await asyncio.get_event_loop().run_in_executor(None, _write)

        storage_path = str(dest_path)
        logger.info(
            "video_saved_local",
            video_id=video_id,
            filename=filename,
            path=storage_path,
        )
        return storage_path

    async def delete_video(self, video_id: str, filepath: str) -> None:
        """Delete the video file and its parent directory if empty."""
        path = Path(filepath)

        def _delete() -> None:
            if path.exists():
                path.unlink()
                # Remove the video_id directory if it is now empty
                parent = path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()

        await asyncio.get_event_loop().run_in_executor(None, _delete)
        logger.info("video_deleted_local", video_id=video_id, filepath=filepath)

    async def get_video_path(self, video_id: str, filepath: str) -> str:
        """Return the absolute local filesystem path for the video."""
        return str(Path(filepath).resolve())


# ---------------------------------------------------------------------------
# S3 storage backend
# ---------------------------------------------------------------------------


class S3StorageBackend(VideoStorageBackend):
    """Stores videos in an S3 (or S3-compatible) bucket using aioboto3."""

    def __init__(
        self,
        bucket: str = S3_BUCKET,
        region: str = S3_REGION,
        access_key: str = S3_ACCESS_KEY,
        secret_key: str = S3_SECRET_KEY,
    ) -> None:
        try:
            import aioboto3  # noqa: F401 — validate availability at construction time
        except ImportError as exc:
            raise ImportError(
                "The 'aioboto3' package is required for S3 storage. "
                "Install it with: pip install aioboto3==12.3.0"
            ) from exc

        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key

    def _session(self):
        """Return a configured aioboto3 Session."""
        import aioboto3

        return aioboto3.Session(
            aws_access_key_id=self.access_key or None,
            aws_secret_access_key=self.secret_key or None,
            region_name=self.region,
        )

    def _key(self, video_id: str, filename: str) -> str:
        return f"videos/{video_id}/{filename}"

    async def save_video(
        self, file_content: bytes, video_id: str, filename: str
    ) -> str:
        """Upload *file_content* to S3 and return the object key."""
        key = self._key(video_id, filename)
        async with self._session().client("s3") as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=file_content,
            )
        logger.info(
            "video_saved_s3",
            video_id=video_id,
            bucket=self.bucket,
            key=key,
        )
        return key

    async def delete_video(self, video_id: str, filepath: str) -> None:
        """Delete the S3 object at *filepath* (treated as the object key)."""
        async with self._session().client("s3") as s3:
            await s3.delete_object(Bucket=self.bucket, Key=filepath)
        logger.info(
            "video_deleted_s3",
            video_id=video_id,
            bucket=self.bucket,
            key=filepath,
        )

    async def get_video_path(self, video_id: str, filepath: str) -> str:
        """Generate and return a presigned URL for the S3 object."""
        async with self._session().client("s3") as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": filepath},
                ExpiresIn=_PRESIGNED_URL_EXPIRY,
            )
        return url


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_storage_backend() -> VideoStorageBackend:
    """Return the appropriate storage backend based on STORAGE_BACKEND env var.

    Raises:
        ValueError: If STORAGE_BACKEND is set to an unrecognised value.
        ImportError: If STORAGE_BACKEND is 's3' but aioboto3 is not installed.
    """
    backend = STORAGE_BACKEND.lower()
    if backend == "local":
        return LocalStorageBackend()
    if backend == "s3":
        return S3StorageBackend()
    raise ValueError(
        f"Unknown STORAGE_BACKEND '{STORAGE_BACKEND}'. "
        "Valid values are 'local' and 's3'."
    )
