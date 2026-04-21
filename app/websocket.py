"""
WebSocket endpoint for real-time video processing progress updates.

Provides:
  - WS /ws/videos/{video_id}/progress — stream progress updates to authenticated clients

Requirements: 6.1, 6.2, 6.3, 6.5
"""

import json
import time

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import _decode_token
from app.redis_client import subscribe

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])

# Maximum number of progress updates per second (Requirement 6.5)
_MAX_UPDATES_PER_SECOND = 2
_MIN_INTERVAL_SECONDS = 1.0 / _MAX_UPDATES_PER_SECOND  # 0.5 seconds


@router.websocket("/ws/videos/{video_id}/progress")
async def video_progress_ws(websocket: WebSocket, video_id: str, token: str = ""):
    """
    Stream processing progress updates for a video to an authenticated WebSocket client.

    Authentication: pass a valid JWT as the `token` query parameter.
    Messages are forwarded from the Redis pub/sub channel `progress:{video_id}`.
    Connection is closed when a message with status "completed" or "failed" is received.

    Requirements: 6.1, 6.2, 6.3, 6.5
    """
    # Accept the connection first so we can send a close code if auth fails
    await websocket.accept()

    # --- Authentication (Requirement 6.1) ---
    try:
        _decode_token(token)
    except Exception:
        logger.warning("websocket_auth_failed", video_id=video_id)
        await websocket.close(code=4001)
        return

    logger.info("websocket_connected", video_id=video_id)

    channel = f"progress:{video_id}"
    pubsub = await subscribe(channel)

    last_send_time: float = 0.0

    try:
        async for message in pubsub.listen():
            # Redis pub/sub yields control messages (type "subscribe") and data messages
            if message.get("type") != "message":
                continue

            data: str = message.get("data", "")

            # --- Throttle: max 2 updates/second (Requirement 6.5) ---
            now = time.monotonic()
            is_terminal = False

            # Parse to check for terminal status before deciding to skip
            try:
                payload = json.loads(data)
                status = payload.get("status", "")
                is_terminal = status in ("completed", "failed")
            except (json.JSONDecodeError, AttributeError):
                is_terminal = False

            # Always send terminal messages; throttle intermediate ones
            if not is_terminal:
                elapsed = now - last_send_time
                if elapsed < _MIN_INTERVAL_SECONDS:
                    continue  # skip this update

            # --- Forward message to client (Requirement 6.2) ---
            await websocket.send_text(data)
            last_send_time = time.monotonic()

            # --- Close on terminal status (Requirement 6.3) ---
            if is_terminal:
                logger.info(
                    "websocket_terminal_status",
                    video_id=video_id,
                    status=status,
                )
                await websocket.close()
                break

    except WebSocketDisconnect:
        # Client disconnected — clean up gracefully
        logger.info("websocket_disconnected", video_id=video_id)
    finally:
        # Always unsubscribe and clean up the pub/sub connection
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception as exc:
            logger.warning("websocket_pubsub_cleanup_error", video_id=video_id, error=str(exc))
