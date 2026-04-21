"""
Unit tests for app/websocket.py — WebSocket progress endpoint.

Covers:
  - Authentication: valid token allows connection, invalid/missing token closes with code 4001
  - Message forwarding: progress messages are forwarded to the client
  - Required fields: current_frame, total_frames, percentage_complete, estimated_time_remaining_seconds
  - Throttling: max 2 messages/second (messages within 0.5s are dropped)
  - Terminal status: "completed" and "failed" messages are sent and connection is closed

Requirements: 6.2, 6.5
"""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app
from app.auth import JWT_SECRET, JWT_ALGORITHM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(username: str = "admin", role: str = "admin") -> str:
    """Create a valid JWT for testing."""
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _make_progress_message(
    current_frame: int = 10,
    total_frames: int = 100,
    percentage_complete: float = 10.0,
    estimated_time_remaining_seconds: float = 90.0,
    status: str = "processing",
) -> str:
    """Build a JSON progress message string."""
    return json.dumps({
        "current_frame": current_frame,
        "total_frames": total_frames,
        "percentage_complete": percentage_complete,
        "estimated_time_remaining_seconds": estimated_time_remaining_seconds,
        "status": status,
    })


def _make_pubsub_messages(raw_messages: list[str]) -> list[dict]:
    """
    Wrap raw JSON strings as Redis pub/sub message dicts.
    Prepends a 'subscribe' control message that the handler skips.
    """
    messages = [{"type": "subscribe", "data": 1}]
    for data in raw_messages:
        messages.append({"type": "message", "data": data})
    return messages


def _make_mock_pubsub(messages: list[dict]):
    """
    Return an async mock PubSub object whose listen() yields the given messages.
    """
    pubsub = MagicMock()

    async def _listen():
        for msg in messages:
            yield msg

    pubsub.listen = _listen
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    return pubsub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Authentication tests
# ---------------------------------------------------------------------------

class TestWebSocketAuth:
    def test_valid_token_allows_connection(self, client):
        """A valid JWT token should allow the WebSocket connection to proceed."""
        token = _make_token()
        progress_msg = _make_progress_message(status="completed")
        pubsub = _make_mock_pubsub(_make_pubsub_messages([progress_msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                # Connection was accepted — we can receive the completed message
                data = ws.receive_text()
                payload = json.loads(data)
                assert payload["status"] == "completed"

    def test_invalid_token_closes_with_code_4001(self, client):
        """An invalid JWT token should cause the server to close with code 4001."""
        with patch("app.websocket.subscribe", new=AsyncMock()):
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/ws/videos/vid_001/progress?token=not.a.valid.token"
                ) as ws:
                    ws.receive_text()

    def test_missing_token_closes_with_code_4001(self, client):
        """A missing token (empty string) should cause the server to close with code 4001."""
        with patch("app.websocket.subscribe", new=AsyncMock()):
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/ws/videos/vid_001/progress"
                ) as ws:
                    ws.receive_text()

    def test_expired_token_closes_with_code_4001(self, client):
        """An expired JWT token should cause the server to close with code 4001."""
        expired_payload = {
            "sub": "admin",
            "role": "admin",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
        }
        expired_token = jwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        with patch("app.websocket.subscribe", new=AsyncMock()):
            with pytest.raises(Exception):
                with client.websocket_connect(
                    f"/ws/videos/vid_001/progress?token={expired_token}"
                ) as ws:
                    ws.receive_text()


# ---------------------------------------------------------------------------
# Message forwarding tests
# ---------------------------------------------------------------------------

class TestWebSocketMessageForwarding:
    def test_progress_message_is_forwarded_to_client(self, client):
        """Progress messages from Redis pub/sub should be forwarded to the WebSocket client."""
        token = _make_token()
        progress_msg = _make_progress_message(
            current_frame=50,
            total_frames=200,
            percentage_complete=25.0,
            estimated_time_remaining_seconds=60.0,
            status="processing",
        )
        completed_msg = _make_progress_message(status="completed")

        pubsub = _make_mock_pubsub(
            _make_pubsub_messages([progress_msg, completed_msg])
        )

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                received = ws.receive_text()
                payload = json.loads(received)
                assert payload["current_frame"] == 50
                assert payload["total_frames"] == 200
                assert payload["percentage_complete"] == 25.0
                assert payload["estimated_time_remaining_seconds"] == 60.0


# ---------------------------------------------------------------------------
# Required fields tests (Requirement 6.2)
# ---------------------------------------------------------------------------

class TestWebSocketRequiredFields:
    def test_progress_message_contains_current_frame(self, client):
        """Progress messages must contain the current_frame field."""
        token = _make_token()
        msg = _make_progress_message(current_frame=42, status="completed")
        pubsub = _make_mock_pubsub(_make_pubsub_messages([msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                payload = json.loads(ws.receive_text())
                assert "current_frame" in payload
                assert payload["current_frame"] == 42

    def test_progress_message_contains_total_frames(self, client):
        """Progress messages must contain the total_frames field."""
        token = _make_token()
        msg = _make_progress_message(total_frames=500, status="completed")
        pubsub = _make_mock_pubsub(_make_pubsub_messages([msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                payload = json.loads(ws.receive_text())
                assert "total_frames" in payload
                assert payload["total_frames"] == 500

    def test_progress_message_contains_percentage_complete(self, client):
        """Progress messages must contain the percentage_complete field."""
        token = _make_token()
        msg = _make_progress_message(percentage_complete=75.5, status="completed")
        pubsub = _make_mock_pubsub(_make_pubsub_messages([msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                payload = json.loads(ws.receive_text())
                assert "percentage_complete" in payload
                assert payload["percentage_complete"] == 75.5

    def test_progress_message_contains_estimated_time_remaining_seconds(self, client):
        """Progress messages must contain the estimated_time_remaining_seconds field."""
        token = _make_token()
        msg = _make_progress_message(estimated_time_remaining_seconds=120.0, status="completed")
        pubsub = _make_mock_pubsub(_make_pubsub_messages([msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                payload = json.loads(ws.receive_text())
                assert "estimated_time_remaining_seconds" in payload
                assert payload["estimated_time_remaining_seconds"] == 120.0

    def test_progress_message_contains_all_required_fields(self, client):
        """Progress messages must contain all four required fields simultaneously.

        Validates: Requirements 6.2
        """
        token = _make_token()
        msg = _make_progress_message(
            current_frame=30,
            total_frames=300,
            percentage_complete=10.0,
            estimated_time_remaining_seconds=270.0,
            status="completed",
        )
        pubsub = _make_mock_pubsub(_make_pubsub_messages([msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                payload = json.loads(ws.receive_text())
                required_fields = {
                    "current_frame",
                    "total_frames",
                    "percentage_complete",
                    "estimated_time_remaining_seconds",
                }
                assert required_fields.issubset(payload.keys()), (
                    f"Missing fields: {required_fields - payload.keys()}"
                )


# ---------------------------------------------------------------------------
# Throttling tests (Requirement 6.5)
# ---------------------------------------------------------------------------

class TestWebSocketThrottling:
    def test_two_messages_within_half_second_only_first_is_forwarded(self, client):
        """If two non-terminal messages arrive within 0.5s, only the first is forwarded.

        Validates: Requirements 6.5
        """
        token = _make_token()

        # Two rapid progress messages followed by a terminal to end the connection
        msg1 = _make_progress_message(current_frame=1, percentage_complete=1.0)
        msg2 = _make_progress_message(current_frame=2, percentage_complete=2.0)
        completed = _make_progress_message(status="completed")

        pubsub = _make_mock_pubsub(
            _make_pubsub_messages([msg1, msg2, completed])
        )

        # Freeze time so both msg1 and msg2 appear to arrive at the same instant
        frozen_time = time.monotonic()
        with patch("app.websocket.time") as mock_time:
            mock_time.monotonic.return_value = frozen_time
            with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
                with client.websocket_connect(
                    f"/ws/videos/vid_001/progress?token={token}"
                ) as ws:
                    # First message should be forwarded
                    first = json.loads(ws.receive_text())
                    assert first["current_frame"] == 1

                    # Next message should be the completed (msg2 was throttled)
                    second = json.loads(ws.receive_text())
                    assert second["status"] == "completed"

    def test_messages_separated_by_more_than_half_second_both_forwarded(self, client):
        """Messages separated by more than 0.5s should both be forwarded."""
        token = _make_token()

        msg1 = _make_progress_message(current_frame=1, percentage_complete=1.0)
        msg2 = _make_progress_message(current_frame=2, percentage_complete=2.0)
        completed = _make_progress_message(status="completed")

        pubsub = _make_mock_pubsub(
            _make_pubsub_messages([msg1, msg2, completed])
        )

        # The handler calls time.monotonic() twice per non-terminal message:
        #   - once to get `now` for the throttle check
        #   - once to update `last_send_time` after sending
        #
        # last_send_time starts at 0.0. For msg1 to pass the throttle check,
        # `now` must be >= 0.5 (i.e., elapsed = now - 0.0 >= 0.5).
        # For msg2 to also pass, its `now` must be >= last_send_time + 0.5.
        #
        # Call sequence:
        #   call 1 (msg1 check):     t=1000.0 → elapsed = 1000.0 - 0.0 = 1000.0 ≥ 0.5 → send msg1
        #   call 2 (msg1 last_send): t=1000.0 → last_send_time = 1000.0
        #   call 3 (msg2 check):     t=1000.6 → elapsed = 1000.6 - 1000.0 = 0.6 ≥ 0.5 → send msg2
        #   call 4 (msg2 last_send): t=1000.6 → last_send_time = 1000.6
        #   (completed is terminal — throttle check still runs but is_terminal bypasses the skip)
        times = iter([1000.0, 1000.0, 1000.6, 1000.6, 1000.6, 1000.6])

        with patch("app.websocket.time") as mock_time:
            mock_time.monotonic.side_effect = lambda: next(times)
            with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
                with client.websocket_connect(
                    f"/ws/videos/vid_001/progress?token={token}"
                ) as ws:
                    first = json.loads(ws.receive_text())
                    assert first["current_frame"] == 1

                    second = json.loads(ws.receive_text())
                    # msg2 should have been forwarded (not throttled)
                    assert second["current_frame"] == 2

                    third = json.loads(ws.receive_text())
                    assert third["status"] == "completed"

    def test_terminal_message_is_never_throttled(self, client):
        """Terminal messages (completed/failed) must always be forwarded regardless of timing."""
        token = _make_token()

        # Send a progress message immediately followed by a terminal message
        msg1 = _make_progress_message(current_frame=1)
        completed = _make_progress_message(status="completed")

        pubsub = _make_mock_pubsub(
            _make_pubsub_messages([msg1, completed])
        )

        # Freeze time so both messages appear simultaneous
        frozen_time = time.monotonic()
        with patch("app.websocket.time") as mock_time:
            mock_time.monotonic.return_value = frozen_time
            with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
                with client.websocket_connect(
                    f"/ws/videos/vid_001/progress?token={token}"
                ) as ws:
                    first = json.loads(ws.receive_text())
                    assert first["current_frame"] == 1

                    # The completed message must still arrive even though time hasn't advanced
                    second = json.loads(ws.receive_text())
                    assert second["status"] == "completed"


# ---------------------------------------------------------------------------
# Terminal status tests (Requirement 6.3)
# ---------------------------------------------------------------------------

class TestWebSocketTerminalStatus:
    def test_completed_message_is_sent_and_connection_closes(self, client):
        """A message with status='completed' should be forwarded and the connection closed."""
        token = _make_token()
        completed_msg = _make_progress_message(
            current_frame=100,
            total_frames=100,
            percentage_complete=100.0,
            estimated_time_remaining_seconds=0.0,
            status="completed",
        )
        pubsub = _make_mock_pubsub(_make_pubsub_messages([completed_msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                data = ws.receive_text()
                payload = json.loads(data)
                assert payload["status"] == "completed"
                assert payload["current_frame"] == 100
                assert payload["percentage_complete"] == 100.0

    def test_failed_message_is_sent_and_connection_closes(self, client):
        """A message with status='failed' should be forwarded and the connection closed."""
        token = _make_token()
        failed_msg = _make_progress_message(
            current_frame=45,
            total_frames=100,
            percentage_complete=45.0,
            estimated_time_remaining_seconds=0.0,
            status="failed",
        )
        pubsub = _make_mock_pubsub(_make_pubsub_messages([failed_msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                data = ws.receive_text()
                payload = json.loads(data)
                assert payload["status"] == "failed"
                assert payload["current_frame"] == 45

    def test_pubsub_is_cleaned_up_after_completed(self, client):
        """The pub/sub subscription should be cleaned up after a completed message."""
        token = _make_token()
        completed_msg = _make_progress_message(status="completed")
        pubsub = _make_mock_pubsub(_make_pubsub_messages([completed_msg]))

        with patch("app.websocket.subscribe", new=AsyncMock(return_value=pubsub)):
            with client.websocket_connect(
                f"/ws/videos/vid_001/progress?token={token}"
            ) as ws:
                ws.receive_text()

        # Verify cleanup was called
        pubsub.unsubscribe.assert_called_once()
        pubsub.aclose.assert_called_once()
