"""
Video validation for the Enhanced Web Dashboard.

Validates uploaded video files for format, size, duration, resolution,
and codec before they are stored or processed.

All validation failures raise ``fastapi.HTTPException`` with a structured
JSON detail body:  ``{"error": "...", "field": "...", "value": ...}``
"""

import json
import subprocess
from fractions import Fraction

from fastapi import HTTPException

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES: int = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_DURATION_SECONDS: float = 4 * 3600  # 4 hours

MIN_HEIGHT: int = 720   # 720p
MAX_HEIGHT: int = 2160  # 4K (2160p)

SUPPORTED_CODECS: set[str] = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}


# ---------------------------------------------------------------------------
# Magic-byte format detection
# ---------------------------------------------------------------------------

def validate_magic_bytes(file_content: bytes) -> str:
    """Detect the video container format from the file's magic bytes.

    Checks for MP4, AVI, and MOV signatures.

    Args:
        file_content: Raw bytes of the uploaded file (at least 12 bytes).

    Returns:
        Detected format string: ``"mp4"``, ``"avi"``, or ``"mov"``.

    Raises:
        HTTPException(422): If the format cannot be identified as a
            supported container type.
    """
    if len(file_content) < 12:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "File too small to determine format",
                "field": "file",
                "value": len(file_content),
            },
        )

    # AVI: RIFF....AVI  (bytes 0-3 == b'RIFF', bytes 8-11 == b'AVI ')
    if file_content[0:4] == b"RIFF" and file_content[8:12] == b"AVI ":
        logger.debug("magic_bytes_detected", format="avi")
        return "avi"

    # MP4 / MOV: ISO Base Media File Format containers share the 'ftyp' box.
    # The box size (4 bytes) precedes the 'ftyp' marker at bytes 4-7.
    # Some files start with a 'wide' or 'free' box before 'ftyp'.
    # We scan the first 32 bytes for known box types.
    _MP4_BRANDS = {
        b"mp41", b"mp42", b"isom", b"iso2", b"iso3", b"iso4", b"iso5",
        b"iso6", b"avc1", b"M4V ", b"M4A ", b"M4P ", b"M4B ", b"MSNV",
        b"NDAS", b"NDSC", b"NDSH", b"NDSM", b"NDSP", b"NDSS", b"NDXC",
        b"NDXH", b"NDXM", b"NDXP", b"NDXS", b"F4V ", b"F4P ",
    }
    _MOV_BRANDS = {
        b"qt  ", b"mqt ",
    }
    _MOV_BOX_TYPES = {b"moov", b"wide", b"mdat", b"free", b"skip", b"pnot"}

    # Check bytes 4-7 for box type
    box_type = file_content[4:8]

    if box_type == b"ftyp" and len(file_content) >= 12:
        # The major brand is at bytes 8-11
        major_brand = file_content[8:12]
        if major_brand in _MP4_BRANDS:
            logger.debug("magic_bytes_detected", format="mp4", brand=major_brand.decode(errors="replace"))
            return "mp4"
        if major_brand in _MOV_BRANDS:
            logger.debug("magic_bytes_detected", format="mov", brand=major_brand.decode(errors="replace"))
            return "mov"
        # Unknown brand under ftyp — treat as mp4 (most common ftyp container)
        logger.debug("magic_bytes_detected", format="mp4", brand=major_brand.decode(errors="replace"))
        return "mp4"

    if box_type in _MOV_BOX_TYPES:
        logger.debug("magic_bytes_detected", format="mov", box_type=box_type.decode(errors="replace"))
        return "mov"

    # Some MP4 files start with a 32-bit big-endian size then 'ftyp' at offset 0
    # (i.e. the very first box IS the ftyp box with size encoded in bytes 0-3)
    if file_content[0:4] in (b"\x00\x00\x00\x18", b"\x00\x00\x00\x1c",
                              b"\x00\x00\x00\x14", b"\x00\x00\x00\x20"):
        if file_content[4:8] == b"ftyp":
            logger.debug("magic_bytes_detected", format="mp4")
            return "mp4"

    raise HTTPException(
        status_code=422,
        detail={
            "error": "Unsupported or unrecognised video format. "
                     "Accepted formats: MP4, AVI, MOV",
            "field": "file",
            "value": file_content[0:12].hex(),
        },
    )


# ---------------------------------------------------------------------------
# File size validation
# ---------------------------------------------------------------------------

def validate_file_size(size_bytes: int) -> None:
    """Reject files that exceed the maximum allowed size.

    Args:
        size_bytes: File size in bytes.

    Raises:
        HTTPException(413): If *size_bytes* > ``MAX_FILE_SIZE_BYTES``.
    """
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": (
                    f"File size {size_bytes} bytes exceeds the maximum "
                    f"allowed size of {MAX_FILE_SIZE_BYTES} bytes (2 GB)"
                ),
                "field": "file_size",
                "value": size_bytes,
            },
        )


# ---------------------------------------------------------------------------
# ffprobe metadata extraction
# ---------------------------------------------------------------------------

def validate_video_metadata(filepath: str) -> dict:
    """Run ``ffprobe`` on *filepath* and return extracted video metadata.

    The returned dict contains:
    - ``duration`` (float): Duration in seconds.
    - ``width`` (int): Frame width in pixels.
    - ``height`` (int): Frame height in pixels.
    - ``codec`` (str): Codec name (lower-cased), e.g. ``"h264"``.
    - ``frame_rate`` (float): Frames per second.

    Args:
        filepath: Absolute or relative path to the video file on disk.

    Returns:
        Metadata dict with the fields listed above.

    Raises:
        HTTPException(422): If ``ffprobe`` is not available, the file
            cannot be probed, or required metadata fields are missing.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        filepath,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ffprobe not available. "
                         "Install FFmpeg to enable video metadata validation.",
                "field": "ffprobe",
                "value": None,
            },
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ffprobe timed out while reading video metadata",
                "field": "ffprobe",
                "value": filepath,
            },
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ffprobe failed to read video metadata. "
                         "The file may be corrupt or in an unsupported format.",
                "field": "file",
                "value": result.stderr.strip() or "unknown error",
            },
        )

    try:
        probe_data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"Failed to parse ffprobe output: {exc}",
                "field": "ffprobe",
                "value": result.stdout[:200],
            },
        )

    # Extract the first video stream
    streams = probe_data.get("streams", [])
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"),
        None,
    )

    if video_stream is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "No video stream found in the uploaded file",
                "field": "file",
                "value": filepath,
            },
        )

    # Duration: prefer stream duration, fall back to format duration
    fmt = probe_data.get("format", {})
    raw_duration = video_stream.get("duration") or fmt.get("duration")
    if raw_duration is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Could not determine video duration from metadata",
                "field": "duration",
                "value": None,
            },
        )
    try:
        duration = float(raw_duration)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"Invalid duration value in metadata: {raw_duration!r}",
                "field": "duration",
                "value": raw_duration,
            },
        )

    # Resolution
    width = video_stream.get("width")
    height = video_stream.get("height")
    if width is None or height is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Could not determine video resolution from metadata",
                "field": "resolution",
                "value": None,
            },
        )

    # Codec
    codec = video_stream.get("codec_name", "").lower()
    if not codec:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Could not determine video codec from metadata",
                "field": "codec",
                "value": None,
            },
        )

    # Frame rate: stored as a rational string like "30000/1001" or "25/1"
    raw_frame_rate = (
        video_stream.get("avg_frame_rate")
        or video_stream.get("r_frame_rate")
        or "0/1"
    )
    try:
        frac = Fraction(raw_frame_rate)
        frame_rate = float(frac) if frac.denominator != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        frame_rate = 0.0

    metadata = {
        "duration": duration,
        "width": int(width),
        "height": int(height),
        "codec": codec,
        "frame_rate": frame_rate,
    }

    logger.info(
        "video_metadata_extracted",
        filepath=filepath,
        duration=duration,
        width=width,
        height=height,
        codec=codec,
        frame_rate=frame_rate,
    )

    return metadata


# ---------------------------------------------------------------------------
# Individual constraint validators
# ---------------------------------------------------------------------------

def validate_duration(duration_seconds: float) -> None:
    """Reject videos whose duration exceeds the maximum allowed length.

    Args:
        duration_seconds: Video duration in seconds.

    Raises:
        HTTPException(422): If *duration_seconds* > ``MAX_DURATION_SECONDS``.
    """
    if duration_seconds > MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Video duration {duration_seconds:.1f}s exceeds the "
                    f"maximum allowed duration of {MAX_DURATION_SECONDS}s (4 hours)"
                ),
                "field": "duration",
                "value": duration_seconds,
            },
        )


def validate_resolution(width: int, height: int) -> None:
    """Reject videos whose resolution is outside the 720p–4K range.

    The check is based on frame height:
    - Minimum: 720 px (720p)
    - Maximum: 2160 px (4K / UHD)

    Args:
        width: Frame width in pixels.
        height: Frame height in pixels.

    Raises:
        HTTPException(422): If *height* < ``MIN_HEIGHT`` or > ``MAX_HEIGHT``.
    """
    if height < MIN_HEIGHT:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Video resolution {width}x{height} is below the minimum "
                    f"supported resolution (height must be >= {MIN_HEIGHT}px / 720p)"
                ),
                "field": "resolution",
                "value": f"{width}x{height}",
            },
        )
    if height > MAX_HEIGHT:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Video resolution {width}x{height} exceeds the maximum "
                    f"supported resolution (height must be <= {MAX_HEIGHT}px / 4K)"
                ),
                "field": "resolution",
                "value": f"{width}x{height}",
            },
        )


def validate_codec(codec: str) -> None:
    """Reject videos encoded with an unsupported codec.

    Args:
        codec: Codec name string (case-insensitive).

    Raises:
        HTTPException(422): If *codec* is not in ``SUPPORTED_CODECS``.
    """
    normalised = codec.lower().strip()
    if normalised not in SUPPORTED_CODECS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Unsupported video codec '{codec}'. "
                    f"Supported codecs: {', '.join(sorted(SUPPORTED_CODECS))}"
                ),
                "field": "codec",
                "value": codec,
            },
        )


# ---------------------------------------------------------------------------
# Orchestrating validator
# ---------------------------------------------------------------------------

def validate_video(file_content: bytes, temp_filepath: str) -> dict:
    """Run all validation checks on an uploaded video file.

    Checks are performed in this order:
    1. Magic bytes (format detection)
    2. File size
    3. ffprobe metadata extraction
    4. Duration
    5. Resolution
    6. Codec

    The file is **not** stored if any check fails — the caller is
    responsible for writing *file_content* to *temp_filepath* before
    calling this function, and for cleaning it up afterwards.

    Args:
        file_content: Raw bytes of the uploaded file.
        temp_filepath: Path to the temporary file on disk (used by ffprobe).

    Returns:
        Metadata dict from :func:`validate_video_metadata` on success,
        augmented with the detected ``"format"`` key.

    Raises:
        HTTPException: With the appropriate status code and structured
            JSON detail body if any validation check fails.
    """
    # 1. Magic bytes — detect container format
    detected_format = validate_magic_bytes(file_content)

    # 2. File size
    validate_file_size(len(file_content))

    # 3. ffprobe metadata
    metadata = validate_video_metadata(temp_filepath)

    # 4. Duration
    validate_duration(metadata["duration"])

    # 5. Resolution
    validate_resolution(metadata["width"], metadata["height"])

    # 6. Codec
    validate_codec(metadata["codec"])

    metadata["format"] = detected_format
    return metadata
