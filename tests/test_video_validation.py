"""
Unit tests for app/video_validation.py

Covers:
- validate_magic_bytes: MP4, AVI, MOV detection and rejection of unknown formats
- validate_file_size: 2 GB limit (HTTP 413)
- validate_duration: 4-hour limit (HTTP 422)
- validate_resolution: 720p–4K range (HTTP 422)
- validate_codec: supported codec set (HTTP 422)
- validate_video_metadata: ffprobe unavailability (HTTP 422)
- validate_video: orchestration order and success path

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

import json
import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.video_validation import (
    MAX_DURATION_SECONDS,
    MAX_FILE_SIZE_BYTES,
    MAX_HEIGHT,
    MIN_HEIGHT,
    SUPPORTED_CODECS,
    validate_codec,
    validate_duration,
    validate_file_size,
    validate_magic_bytes,
    validate_resolution,
    validate_video,
    validate_video_metadata,
)


# ---------------------------------------------------------------------------
# Helpers — minimal magic-byte headers
# ---------------------------------------------------------------------------

def _mp4_header() -> bytes:
    """Minimal ftyp box header recognised as MP4 (isom brand)."""
    # box_size(4) + 'ftyp'(4) + major_brand(4) + minor_version(4) = 16 bytes
    return b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00"


def _avi_header() -> bytes:
    """Minimal RIFF/AVI header."""
    return b"RIFF\x00\x00\x00\x00AVI LIST"


def _mov_header() -> bytes:
    """Minimal QuickTime 'moov' box header."""
    return b"\x00\x00\x00\x08moov" + b"\x00" * 4


def _qt_ftyp_header() -> bytes:
    """ftyp box with QuickTime 'qt  ' brand — recognised as MOV."""
    return b"\x00\x00\x00\x10ftypqt  \x00\x00\x00\x00"


def _unknown_header() -> bytes:
    """Bytes that do not match any supported format."""
    return b"\xff\xfb\x90\x00" + b"\x00" * 12


# ---------------------------------------------------------------------------
# validate_magic_bytes
# ---------------------------------------------------------------------------

class TestValidateMagicBytes:
    def test_mp4_isom_brand(self):
        assert validate_magic_bytes(_mp4_header()) == "mp4"

    def test_avi_riff_header(self):
        assert validate_magic_bytes(_avi_header()) == "avi"

    def test_mov_moov_box(self):
        assert validate_magic_bytes(_mov_header()) == "mov"

    def test_mov_qt_ftyp_brand(self):
        assert validate_magic_bytes(_qt_ftyp_header()) == "mov"

    def test_mp4_wide_ftyp_prefix(self):
        # Some MP4 files start with a 0x1c-byte ftyp box
        header = b"\x00\x00\x00\x1cftypisom\x00\x00\x00\x00" + b"\x00" * 4
        assert validate_magic_bytes(header) == "mp4"

    def test_unknown_format_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_magic_bytes(_unknown_header())
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["field"] == "file"

    def test_too_short_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_magic_bytes(b"\x00\x01\x02")
        assert exc_info.value.status_code == 422

    def test_error_detail_is_structured(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_magic_bytes(_unknown_header())
        detail = exc_info.value.detail
        assert "error" in detail
        assert "field" in detail
        assert "value" in detail

    def test_mov_wide_box(self):
        header = b"\x00\x00\x00\x08wide" + b"\x00" * 8
        assert validate_magic_bytes(header) == "mov"

    def test_mov_mdat_box(self):
        header = b"\x00\x00\x00\x08mdat" + b"\x00" * 8
        assert validate_magic_bytes(header) == "mov"


# ---------------------------------------------------------------------------
# validate_file_size
# ---------------------------------------------------------------------------

class TestValidateFileSize:
    def test_exactly_at_limit_passes(self):
        # Should not raise
        validate_file_size(MAX_FILE_SIZE_BYTES)

    def test_one_byte_over_limit_raises_413(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(MAX_FILE_SIZE_BYTES + 1)
        assert exc_info.value.status_code == 413

    def test_zero_bytes_passes(self):
        validate_file_size(0)

    def test_small_file_passes(self):
        validate_file_size(1024 * 1024)  # 1 MB

    def test_error_detail_is_structured(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(MAX_FILE_SIZE_BYTES + 1)
        detail = exc_info.value.detail
        assert "error" in detail
        assert detail["field"] == "file_size"
        assert detail["value"] == MAX_FILE_SIZE_BYTES + 1

    def test_exactly_2gb_passes(self):
        validate_file_size(2 * 1024 * 1024 * 1024)


# ---------------------------------------------------------------------------
# validate_duration
# ---------------------------------------------------------------------------

class TestValidateDuration:
    def test_exactly_at_limit_passes(self):
        validate_duration(MAX_DURATION_SECONDS)

    def test_one_second_over_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_duration(MAX_DURATION_SECONDS + 1)
        assert exc_info.value.status_code == 422

    def test_zero_duration_passes(self):
        validate_duration(0.0)

    def test_typical_duration_passes(self):
        validate_duration(3600.0)  # 1 hour

    def test_error_detail_is_structured(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_duration(MAX_DURATION_SECONDS + 100)
        detail = exc_info.value.detail
        assert "error" in detail
        assert detail["field"] == "duration"
        assert detail["value"] == MAX_DURATION_SECONDS + 100

    def test_just_under_limit_passes(self):
        validate_duration(MAX_DURATION_SECONDS - 0.001)


# ---------------------------------------------------------------------------
# validate_resolution
# ---------------------------------------------------------------------------

class TestValidateResolution:
    def test_720p_passes(self):
        validate_resolution(1280, 720)

    def test_1080p_passes(self):
        validate_resolution(1920, 1080)

    def test_4k_passes(self):
        validate_resolution(3840, 2160)

    def test_below_720p_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_resolution(1280, 719)
        assert exc_info.value.status_code == 422

    def test_above_4k_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_resolution(7680, 2161)
        assert exc_info.value.status_code == 422

    def test_min_height_boundary_passes(self):
        validate_resolution(1280, MIN_HEIGHT)

    def test_max_height_boundary_passes(self):
        validate_resolution(3840, MAX_HEIGHT)

    def test_error_detail_below_min(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_resolution(640, 480)
        detail = exc_info.value.detail
        assert "error" in detail
        assert detail["field"] == "resolution"
        assert "640x480" in str(detail["value"])

    def test_error_detail_above_max(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_resolution(7680, 4320)
        detail = exc_info.value.detail
        assert detail["field"] == "resolution"


# ---------------------------------------------------------------------------
# validate_codec
# ---------------------------------------------------------------------------

class TestValidateCodec:
    @pytest.mark.parametrize("codec", sorted(SUPPORTED_CODECS))
    def test_supported_codecs_pass(self, codec):
        validate_codec(codec)

    def test_codec_case_insensitive(self):
        validate_codec("H264")
        validate_codec("HEVC")
        validate_codec("VP9")

    def test_unsupported_codec_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_codec("wmv")
        assert exc_info.value.status_code == 422

    def test_empty_codec_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_codec("")
        assert exc_info.value.status_code == 422

    def test_error_detail_is_structured(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_codec("divx")
        detail = exc_info.value.detail
        assert "error" in detail
        assert detail["field"] == "codec"
        assert detail["value"] == "divx"

    def test_xvid_unsupported(self):
        with pytest.raises(HTTPException):
            validate_codec("xvid")

    def test_h264_supported(self):
        validate_codec("h264")

    def test_av1_supported(self):
        validate_codec("av1")


# ---------------------------------------------------------------------------
# validate_video_metadata — mocked ffprobe
# ---------------------------------------------------------------------------

def _make_ffprobe_output(
    duration="60.0",
    width=1920,
    height=1080,
    codec_name="h264",
    avg_frame_rate="30/1",
) -> str:
    return json.dumps({
        "streams": [
            {
                "codec_type": "video",
                "codec_name": codec_name,
                "width": width,
                "height": height,
                "duration": duration,
                "avg_frame_rate": avg_frame_rate,
                "r_frame_rate": avg_frame_rate,
            }
        ],
        "format": {
            "duration": duration,
        },
    })


class TestValidateVideoMetadata:
    def test_ffprobe_not_found_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        fake_file.write_bytes(b"\x00" * 16)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(HTTPException) as exc_info:
                validate_video_metadata(str(fake_file))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["field"] == "ffprobe"

    def test_ffprobe_nonzero_exit_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        fake_file.write_bytes(b"\x00" * 16)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Invalid data found"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(HTTPException) as exc_info:
                validate_video_metadata(str(fake_file))
        assert exc_info.value.status_code == 422

    def test_valid_metadata_returned(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        fake_file.write_bytes(b"\x00" * 16)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_ffprobe_output(
            duration="120.5",
            width=1920,
            height=1080,
            codec_name="h264",
            avg_frame_rate="30/1",
        )

        with patch("subprocess.run", return_value=mock_result):
            meta = validate_video_metadata(str(fake_file))

        assert meta["duration"] == pytest.approx(120.5)
        assert meta["width"] == 1920
        assert meta["height"] == 1080
        assert meta["codec"] == "h264"
        assert meta["frame_rate"] == pytest.approx(30.0)

    def test_no_video_stream_raises_422(self, tmp_path):
        fake_file = tmp_path / "audio.mp3"
        fake_file.write_bytes(b"\x00" * 16)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "60.0"},
        })

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(HTTPException) as exc_info:
                validate_video_metadata(str(fake_file))
        assert exc_info.value.status_code == 422

    def test_fractional_frame_rate_parsed(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        fake_file.write_bytes(b"\x00" * 16)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_ffprobe_output(avg_frame_rate="30000/1001")

        with patch("subprocess.run", return_value=mock_result):
            meta = validate_video_metadata(str(fake_file))

        assert meta["frame_rate"] == pytest.approx(30000 / 1001, rel=1e-4)

    def test_timeout_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        fake_file.write_bytes(b"\x00" * 16)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=60)):
            with pytest.raises(HTTPException) as exc_info:
                validate_video_metadata(str(fake_file))
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# validate_video — orchestration
# ---------------------------------------------------------------------------

class TestValidateVideo:
    def _mock_run(self, duration="3600.0", width=1920, height=1080,
                  codec="h264", frame_rate="30/1"):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_ffprobe_output(
            duration=duration,
            width=width,
            height=height,
            codec_name=codec,
            avg_frame_rate=frame_rate,
        )
        return mock_result

    def test_valid_video_returns_metadata(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run()):
            meta = validate_video(content, str(fake_file))

        assert meta["format"] == "mp4"
        assert meta["codec"] == "h264"
        assert meta["width"] == 1920
        assert meta["height"] == 1080

    def test_bad_magic_bytes_raises_before_size_check(self, tmp_path):
        """Magic bytes check runs first — bad format raises 422 even for small files."""
        fake_file = tmp_path / "video.bin"
        content = _unknown_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with pytest.raises(HTTPException) as exc_info:
            validate_video(content, str(fake_file))
        assert exc_info.value.status_code == 422

    def test_oversized_file_raises_413(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        oversized = MAX_FILE_SIZE_BYTES + 1
        # Patch len() indirectly by passing a fake large content object
        large_content = bytearray(oversized)
        large_content[:len(_mp4_header())] = _mp4_header()

        with pytest.raises(HTTPException) as exc_info:
            validate_video(bytes(large_content), str(fake_file))
        assert exc_info.value.status_code == 413

    def test_duration_too_long_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run(duration="14401.0")):
            with pytest.raises(HTTPException) as exc_info:
                validate_video(content, str(fake_file))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["field"] == "duration"

    def test_resolution_too_low_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run(width=640, height=480)):
            with pytest.raises(HTTPException) as exc_info:
                validate_video(content, str(fake_file))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["field"] == "resolution"

    def test_resolution_too_high_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run(width=7680, height=4320)):
            with pytest.raises(HTTPException) as exc_info:
                validate_video(content, str(fake_file))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["field"] == "resolution"

    def test_unsupported_codec_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run(codec="wmv3")):
            with pytest.raises(HTTPException) as exc_info:
                validate_video(content, str(fake_file))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["field"] == "codec"

    def test_avi_format_detected(self, tmp_path):
        fake_file = tmp_path / "video.avi"
        content = _avi_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run()):
            meta = validate_video(content, str(fake_file))

        assert meta["format"] == "avi"

    def test_mov_format_detected(self, tmp_path):
        fake_file = tmp_path / "video.mov"
        content = _mov_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", return_value=self._mock_run()):
            meta = validate_video(content, str(fake_file))

        assert meta["format"] == "mov"

    def test_ffprobe_unavailable_raises_422(self, tmp_path):
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(HTTPException) as exc_info:
                validate_video(content, str(fake_file))
        assert exc_info.value.status_code == 422
        assert "ffprobe" in str(exc_info.value.detail["error"]).lower()

    def test_all_error_details_are_structured(self, tmp_path):
        """Every HTTPException raised must have error/field/value keys."""
        fake_file = tmp_path / "video.mp4"
        content = _mp4_header() + b"\x00" * 100
        fake_file.write_bytes(content)

        scenarios = [
            self._mock_run(duration="99999.0"),   # too long
            self._mock_run(width=320, height=240),  # too low
            self._mock_run(codec="flv1"),           # bad codec
        ]

        for mock_result in scenarios:
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(HTTPException) as exc_info:
                    validate_video(content, str(fake_file))
                detail = exc_info.value.detail
                assert "error" in detail, f"Missing 'error' key in {detail}"
                assert "field" in detail, f"Missing 'field' key in {detail}"
                assert "value" in detail, f"Missing 'value' key in {detail}"
