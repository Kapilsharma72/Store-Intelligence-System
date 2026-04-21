"""
Analytics endpoints for the Enhanced Web Dashboard.

Requirements: 7.1, 7.2, 8.1, 8.2, 9.1, 9.2, 10.1, 10.2, 10.5,
              11.1, 11.2, 11.5, 12.1, 12.2, 12.5, 13.1, 13.2, 13.5,
              14.1, 14.2, 14.5, 29.1, 29.2, 29.3, 29.4, 29.5
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user
from app.database import get_db
from app.models import Event as EventModel
from app.redis_client import cache_get, cache_set
from app.videos import _check_ownership, _get_video_or_404

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/videos", tags=["analytics"])

CACHE_TTL_SECONDS = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Cache helper
# ---------------------------------------------------------------------------


async def _get_cached_or_compute(
    cache_key: str,
    compute_fn: Callable,
    response: Response,
) -> Tuple[Any, bool]:
    """
    Try to return a cached result for *cache_key*.

    - On HIT: deserialise the JSON string, set ``X-Cache-Status: HIT``, return (data, True).
    - On MISS: call ``compute_fn()``, serialise to JSON, store in Redis with 1-hour TTL,
      set ``X-Cache-Status: MISS``, return (data, False).

    Requirements: 29.1, 29.2, 29.3, 29.5
    """
    import time as _time

    cached = await cache_get(cache_key)
    if cached is not None:
        response.headers["X-Cache-Status"] = "HIT"
        logger.info("analytics_cache_hit", cache_key=cache_key)
        return json.loads(cached), True

    _compute_start = _time.monotonic()
    data = compute_fn()
    _compute_ms = round((_time.monotonic() - _compute_start) * 1000, 2)

    # Serialise Pydantic models or plain dicts to JSON
    if hasattr(data, "model_dump_json"):
        json_str = data.model_dump_json()
    else:
        json_str = json.dumps(data)
    await cache_set(cache_key, json_str, ttl_seconds=CACHE_TTL_SECONDS)
    response.headers["X-Cache-Status"] = "MISS"
    logger.info("analytics_cache_miss", cache_key=cache_key, compute_ms=_compute_ms)
    return data, False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ts_aware(ts: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _get_video_events(video_id: str, db: Session) -> list:
    """Return all events for a video ordered by timestamp."""
    import time as _time
    _t0 = _time.monotonic()
    result = (
        db.query(EventModel)
        .filter(EventModel.metadata_["video_id"].as_string() == video_id)
        .order_by(EventModel.timestamp)
        .all()
    )
    logger.debug(
        "db_query_duration",
        query="get_video_events",
        video_id=video_id,
        duration_ms=round((_time.monotonic() - _t0) * 1000, 2),
        row_count=len(result),
    )
    return result


def _normalize_0_100(values: list) -> list:
    """Normalize a list of floats to 0-100 scale. Returns 50s if all equal."""
    if not values:
        return values
    mn, mx = min(values), max(values)
    if mx == mn:
        return [50.0] * len(values)
    return [round((v - mn) / (mx - mn) * 100, 2) for v in values]


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class ZoneTransition(BaseModel):
    zone_id: str
    entry_timestamp: Optional[datetime]
    exit_timestamp: Optional[datetime]
    dwell_time_seconds: Optional[float]


class VisitorJourney(BaseModel):
    visitor_id: str
    transitions: List[ZoneTransition]


class JourneyResponse(BaseModel):
    video_id: str
    visitors: List[VisitorJourney]


class TimeseriesInterval(BaseModel):
    interval_start: datetime
    interval_end: datetime
    unique_visitors_cumulative: int
    conversion_rate: float
    queue_depth: int
    avg_dwell_seconds: float


class TimeseriesResponse(BaseModel):
    video_id: str
    interval_seconds: int = 30
    intervals: List[TimeseriesInterval]


class VideoMetrics(BaseModel):
    video_id: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_seconds: float
    queue_depth: int
    normalized_unique_visitors: float = 0.0
    normalized_conversion_rate: float = 0.0
    normalized_avg_dwell_seconds: float = 0.0
    normalized_queue_depth: float = 0.0


class ComparisonResponse(BaseModel):
    base_video_id: str
    videos: List[VideoMetrics]


class StaffAnalysisResponse(BaseModel):
    video_id: str
    staff_count: int
    customer_count: int
    staff_zone_visits: int
    customer_zone_visits: int
    staff_to_customer_ratio: float


class PeakHourInterval(BaseModel):
    interval_start: datetime
    interval_end: datetime
    unique_visitors: int
    purchases: int
    avg_queue_depth: float
    is_peak: bool


class PeakHoursResponse(BaseModel):
    video_id: str
    interval_minutes: int = 15
    intervals: List[PeakHourInterval]


class ZoneRanking(BaseModel):
    zone_id: str
    visit_count: int
    avg_dwell_seconds: float
    conversion_rate: float
    performance_score: float


class ZoneRankingResponse(BaseModel):
    video_id: str
    zones: List[ZoneRanking]


class HighWaitPeriod(BaseModel):
    period_start: datetime
    period_end: datetime
    avg_wait_seconds: float


class QueueAnalysisResponse(BaseModel):
    video_id: str
    avg_wait_time_seconds: float
    max_wait_time_seconds: float
    abandonment_count: int
    abandonment_rate: float
    high_wait_periods: List[HighWaitPeriod]


class DwellBucket(BaseModel):
    bucket_start_seconds: int
    bucket_end_seconds: int
    count: int


class DwellDistributionResponse(BaseModel):
    video_id: str
    bucket_size_seconds: int = 30
    buckets: List[DwellBucket]
    median_dwell_seconds: float
    mean_dwell_seconds: float
    p95_dwell_seconds: float


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/journey
# ---------------------------------------------------------------------------


@router.get("/{video_id}/journey", response_model=JourneyResponse)
async def get_journey(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> JourneyResponse:
    """
    Return visitor zone transitions with entry/exit timestamps and dwell time,
    ordered chronologically per visitor.

    Requirements: 7.1, 7.2, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:journey"

    def compute() -> JourneyResponse:
        events = (
            db.query(EventModel)
            .filter(
                EventModel.metadata_["video_id"].as_string() == video_id,
                EventModel.event_type.in_(["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"]),
            )
            .order_by(EventModel.timestamp)
            .all()
        )

        # Group by visitor_id, then build transitions
        visitor_events: Dict[str, list] = defaultdict(list)
        for ev in events:
            visitor_events[ev.visitor_id].append(ev)

        visitors: List[VisitorJourney] = []
        for visitor_id, evs in visitor_events.items():
            transitions: List[ZoneTransition] = []
            # Track open zone entries: zone_id -> entry event
            open_entries: Dict[str, object] = {}

            for ev in evs:
                if ev.event_type == "ZONE_ENTER":
                    open_entries[ev.zone_id] = ev
                elif ev.event_type == "ZONE_EXIT":
                    entry_ev = open_entries.pop(ev.zone_id, None)
                    entry_ts = entry_ev.timestamp if entry_ev else None
                    dwell = None
                    if entry_ts is not None:
                        dwell = round((_ts_aware(ev.timestamp) - _ts_aware(entry_ts)).total_seconds(), 2)
                    transitions.append(
                        ZoneTransition(
                            zone_id=ev.zone_id or "",
                            entry_timestamp=entry_ts,
                            exit_timestamp=ev.timestamp,
                            dwell_time_seconds=dwell,
                        )
                    )
                elif ev.event_type == "ZONE_DWELL":
                    # ZONE_DWELL carries dwell_ms; use as standalone if no open entry
                    if ev.zone_id not in open_entries:
                        dwell_s = (ev.dwell_ms / 1000.0) if ev.dwell_ms else None
                        transitions.append(
                            ZoneTransition(
                                zone_id=ev.zone_id or "",
                                entry_timestamp=ev.timestamp,
                                exit_timestamp=None,
                                dwell_time_seconds=dwell_s,
                            )
                        )

            # Flush any still-open entries (no EXIT seen)
            for zone_id, entry_ev in open_entries.items():
                transitions.append(
                    ZoneTransition(
                        zone_id=zone_id,
                        entry_timestamp=entry_ev.timestamp,
                        exit_timestamp=None,
                        dwell_time_seconds=None,
                    )
                )

            # Sort transitions by entry_timestamp
            transitions.sort(
                key=lambda t: _ts_aware(t.entry_timestamp) if t.entry_timestamp else datetime.min.replace(tzinfo=timezone.utc)
            )
            visitors.append(VisitorJourney(visitor_id=visitor_id, transitions=transitions))

        return JourneyResponse(video_id=video_id, visitors=visitors)

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return JourneyResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/timeseries
# ---------------------------------------------------------------------------


@router.get("/{video_id}/timeseries", response_model=TimeseriesResponse)
async def get_timeseries(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> TimeseriesResponse:
    """
    Return metrics at 30-second intervals throughout the video duration.

    Metrics per interval:
      - unique_visitors_cumulative: distinct ENTRY visitor_ids up to interval end
      - conversion_rate: BILLING_QUEUE_JOIN visitors / unique_visitors_cumulative
      - queue_depth: net joins - abandons in this interval (min 0)
      - avg_dwell_seconds: mean dwell_ms/1000 from ZONE_DWELL events in interval

    Requirements: 8.1, 8.2, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:timeseries"

    def compute() -> TimeseriesResponse:
        events = _get_video_events(video_id, db)
        if not events:
            return TimeseriesResponse(video_id=video_id, intervals=[])

        min_ts = _ts_aware(events[0].timestamp)
        max_ts = _ts_aware(events[-1].timestamp)

        interval_secs = 30
        intervals: List[TimeseriesInterval] = []

        current_start = min_ts
        while current_start <= max_ts:
            current_end = current_start + timedelta(seconds=interval_secs)

            # Cumulative ENTRY visitors up to current_end
            cumulative_visitors = {
                ev.visitor_id
                for ev in events
                if _ts_aware(ev.timestamp) < current_end
                and ev.event_type == "ENTRY"
                and not ev.is_staff
            }

            # Cumulative queue joins up to current_end
            cumulative_queue_joins = {
                ev.visitor_id
                for ev in events
                if _ts_aware(ev.timestamp) < current_end
                and ev.event_type == "BILLING_QUEUE_JOIN"
                and not ev.is_staff
            }

            uv = len(cumulative_visitors)
            qj = len(cumulative_queue_joins)
            conversion_rate = round(min(1.0, qj / uv), 4) if uv > 0 else 0.0

            # Queue depth: net joins - abandons in this specific interval
            interval_events = [
                ev for ev in events
                if _ts_aware(ev.timestamp) >= current_start
                and _ts_aware(ev.timestamp) < current_end
            ]
            interval_joins = sum(
                1 for ev in interval_events
                if ev.event_type == "BILLING_QUEUE_JOIN" and not ev.is_staff
            )
            interval_abandons = sum(
                1 for ev in interval_events
                if ev.event_type == "BILLING_QUEUE_ABANDON" and not ev.is_staff
            )
            queue_depth = max(0, interval_joins - interval_abandons)

            # avg_dwell in this interval
            dwell_values = [
                ev.dwell_ms / 1000.0
                for ev in interval_events
                if ev.event_type == "ZONE_DWELL" and ev.dwell_ms is not None and not ev.is_staff
            ]
            avg_dwell = round(statistics.mean(dwell_values), 2) if dwell_values else 0.0

            intervals.append(
                TimeseriesInterval(
                    interval_start=current_start,
                    interval_end=current_end,
                    unique_visitors_cumulative=uv,
                    conversion_rate=conversion_rate,
                    queue_depth=queue_depth,
                    avg_dwell_seconds=avg_dwell,
                )
            )

            current_start = current_end

        return TimeseriesResponse(video_id=video_id, intervals=intervals)

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return TimeseriesResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/comparison
# ---------------------------------------------------------------------------


def _compute_raw_metrics(video_id: str, db: Session) -> dict:
    """Compute raw (un-normalized) metrics for a single video."""
    events = (
        db.query(EventModel)
        .filter(EventModel.metadata_["video_id"].as_string() == video_id)
        .all()
    )

    unique_visitors = len({
        ev.visitor_id for ev in events
        if ev.event_type == "ENTRY" and not ev.is_staff
    })

    queue_joins = {
        ev.visitor_id for ev in events
        if ev.event_type == "BILLING_QUEUE_JOIN" and not ev.is_staff
    }
    queue_abandons = sum(
        1 for ev in events
        if ev.event_type == "BILLING_QUEUE_ABANDON" and not ev.is_staff
    )
    queue_depth = max(0, len(queue_joins) - queue_abandons)
    conversion_rate = round(min(1.0, len(queue_joins) / unique_visitors), 4) if unique_visitors > 0 else 0.0

    dwell_values = [
        ev.dwell_ms / 1000.0
        for ev in events
        if ev.event_type == "ZONE_DWELL" and ev.dwell_ms is not None and not ev.is_staff
    ]
    avg_dwell = round(statistics.mean(dwell_values), 2) if dwell_values else 0.0

    return {
        "video_id": video_id,
        "unique_visitors": unique_visitors,
        "conversion_rate": conversion_rate,
        "avg_dwell_seconds": avg_dwell,
        "queue_depth": queue_depth,
    }


@router.get("/{video_id}/comparison", response_model=ComparisonResponse)
async def get_comparison(
    video_id: str,
    response: Response,
    comparison_video_ids: List[str] = Query(default=[]),
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> ComparisonResponse:
    """
    Return normalized 0-100 metrics for the base video and requested comparison videos.

    Requirements: 9.1, 9.2, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    # Include sorted comparison IDs in cache key for determinism
    sorted_comparison = ",".join(sorted(v for v in comparison_video_ids if v != video_id))
    cache_key = f"analytics:{video_id}:comparison:{sorted_comparison}"

    def compute() -> ComparisonResponse:
        all_video_ids = [video_id] + [v for v in comparison_video_ids if v != video_id]

        raw_list = [_compute_raw_metrics(vid, db) for vid in all_video_ids]

        # Normalize each metric across all videos
        norm_uv = _normalize_0_100([float(r["unique_visitors"]) for r in raw_list])
        norm_cr = _normalize_0_100([r["conversion_rate"] for r in raw_list])
        norm_dw = _normalize_0_100([r["avg_dwell_seconds"] for r in raw_list])
        norm_qd = _normalize_0_100([float(r["queue_depth"]) for r in raw_list])

        result_videos: List[VideoMetrics] = []
        for i, raw in enumerate(raw_list):
            result_videos.append(
                VideoMetrics(
                    video_id=raw["video_id"],
                    unique_visitors=raw["unique_visitors"],
                    conversion_rate=raw["conversion_rate"],
                    avg_dwell_seconds=raw["avg_dwell_seconds"],
                    queue_depth=raw["queue_depth"],
                    normalized_unique_visitors=norm_uv[i],
                    normalized_conversion_rate=norm_cr[i],
                    normalized_avg_dwell_seconds=norm_dw[i],
                    normalized_queue_depth=norm_qd[i],
                )
            )

        return ComparisonResponse(base_video_id=video_id, videos=result_videos)

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return ComparisonResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/staff-analysis
# ---------------------------------------------------------------------------


@router.get("/{video_id}/staff-analysis", response_model=StaffAnalysisResponse)
async def get_staff_analysis(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> StaffAnalysisResponse:
    """
    Return staff vs customer breakdown: counts, zone visits, and ratio.
    Staff events are excluded from customer metrics.

    Requirements: 10.1, 10.2, 10.5, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:staff-analysis"

    def compute() -> StaffAnalysisResponse:
        events = _get_video_events(video_id, db)

        staff_visitors: set = set()
        customer_visitors: set = set()
        staff_zone_visits = 0
        customer_zone_visits = 0

        for ev in events:
            if ev.is_staff:
                staff_visitors.add(ev.visitor_id)
                if ev.event_type == "ZONE_ENTER":
                    staff_zone_visits += 1
            else:
                customer_visitors.add(ev.visitor_id)
                if ev.event_type == "ZONE_ENTER":
                    customer_zone_visits += 1

        staff_count = len(staff_visitors)
        customer_count = len(customer_visitors)
        ratio = round(staff_count / customer_count, 4) if customer_count > 0 else 0.0

        return StaffAnalysisResponse(
            video_id=video_id,
            staff_count=staff_count,
            customer_count=customer_count,
            staff_zone_visits=staff_zone_visits,
            customer_zone_visits=customer_zone_visits,
            staff_to_customer_ratio=ratio,
        )

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return StaffAnalysisResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/peak-hours
# ---------------------------------------------------------------------------


@router.get("/{video_id}/peak-hours", response_model=PeakHoursResponse)
async def get_peak_hours(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> PeakHoursResponse:
    """
    Divide video duration into 15-minute intervals ranked by traffic.
    Top 3 intervals are flagged as peak.

    Requirements: 11.1, 11.2, 11.5, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:peak-hours"

    def compute() -> PeakHoursResponse:
        events = _get_video_events(video_id, db)
        if not events:
            return PeakHoursResponse(video_id=video_id, intervals=[])

        min_ts = _ts_aware(events[0].timestamp)
        max_ts = _ts_aware(events[-1].timestamp)

        interval_delta = timedelta(minutes=15)
        interval_data: List[dict] = []

        current_start = min_ts
        while current_start <= max_ts:
            current_end = current_start + interval_delta
            interval_events = [
                ev for ev in events
                if _ts_aware(ev.timestamp) >= current_start
                and _ts_aware(ev.timestamp) < current_end
            ]

            unique_visitors = len({
                ev.visitor_id for ev in interval_events
                if ev.event_type == "ENTRY" and not ev.is_staff
            })
            purchases = sum(
                1 for ev in interval_events
                if ev.event_type == "BILLING_QUEUE_JOIN" and not ev.is_staff
            )
            joins = sum(1 for ev in interval_events if ev.event_type == "BILLING_QUEUE_JOIN" and not ev.is_staff)
            abandons = sum(1 for ev in interval_events if ev.event_type == "BILLING_QUEUE_ABANDON" and not ev.is_staff)
            avg_queue_depth = float(max(0, joins - abandons))

            interval_data.append({
                "interval_start": current_start,
                "interval_end": current_end,
                "unique_visitors": unique_visitors,
                "purchases": purchases,
                "avg_queue_depth": avg_queue_depth,
            })
            current_start = current_end

        # Flag top 3 by unique_visitors as peak
        sorted_by_traffic = sorted(interval_data, key=lambda x: x["unique_visitors"], reverse=True)
        peak_starts = {d["interval_start"] for d in sorted_by_traffic[:3]}

        intervals: List[PeakHourInterval] = [
            PeakHourInterval(
                interval_start=d["interval_start"],
                interval_end=d["interval_end"],
                unique_visitors=d["unique_visitors"],
                purchases=d["purchases"],
                avg_queue_depth=d["avg_queue_depth"],
                is_peak=d["interval_start"] in peak_starts,
            )
            for d in interval_data
        ]

        return PeakHoursResponse(video_id=video_id, intervals=intervals)

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return PeakHoursResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/zone-ranking
# ---------------------------------------------------------------------------


@router.get("/{video_id}/zone-ranking", response_model=ZoneRankingResponse)
async def get_zone_ranking(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> ZoneRankingResponse:
    """
    Return zones sorted by performance_score (0-100).

    performance_score = (conversion_rate * 50 + normalized_avg_dwell * 50) clamped 0-100.
    conversion_rate per zone = visitors who entered zone AND later had BILLING_QUEUE_JOIN
                               / total zone visitors.

    Requirements: 12.1, 12.2, 12.5, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:zone-ranking"

    def compute() -> ZoneRankingResponse:
        events = _get_video_events(video_id, db)

        zone_visitors: Dict[str, set] = defaultdict(set)
        zone_dwell_ms: Dict[str, list] = defaultdict(list)
        purchasers: set = set()

        for ev in events:
            if ev.is_staff:
                continue
            if ev.event_type == "ZONE_ENTER" and ev.zone_id:
                zone_visitors[ev.zone_id].add(ev.visitor_id)
            elif ev.event_type == "ZONE_DWELL" and ev.zone_id and ev.dwell_ms is not None:
                zone_dwell_ms[ev.zone_id].append(ev.dwell_ms)
            elif ev.event_type == "BILLING_QUEUE_JOIN":
                purchasers.add(ev.visitor_id)

        if not zone_visitors:
            return ZoneRankingResponse(video_id=video_id, zones=[])

        zone_metrics: List[dict] = []
        for zone_id, visitors in zone_visitors.items():
            visit_count = len(visitors)
            converters = len(visitors & purchasers)
            conversion_rate = round(converters / visit_count, 4) if visit_count > 0 else 0.0

            dwell_list = zone_dwell_ms.get(zone_id, [])
            avg_dwell_s = round(statistics.mean(dwell_list) / 1000.0, 2) if dwell_list else 0.0

            zone_metrics.append({
                "zone_id": zone_id,
                "visit_count": visit_count,
                "avg_dwell_seconds": avg_dwell_s,
                "conversion_rate": conversion_rate,
            })

        # Normalize avg_dwell across zones for performance_score
        dwell_vals = [z["avg_dwell_seconds"] for z in zone_metrics]
        max_dwell = max(dwell_vals) if dwell_vals else 1.0
        if max_dwell == 0:
            max_dwell = 1.0

        zones: List[ZoneRanking] = []
        for z in zone_metrics:
            norm_dwell = z["avg_dwell_seconds"] / max_dwell
            perf = z["conversion_rate"] * 50.0 + norm_dwell * 50.0
            perf = round(max(0.0, min(100.0, perf)), 2)
            zones.append(
                ZoneRanking(
                    zone_id=z["zone_id"],
                    visit_count=z["visit_count"],
                    avg_dwell_seconds=z["avg_dwell_seconds"],
                    conversion_rate=z["conversion_rate"],
                    performance_score=perf,
                )
            )

        zones.sort(key=lambda z: z.performance_score, reverse=True)
        return ZoneRankingResponse(video_id=video_id, zones=zones)

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return ZoneRankingResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/queue-analysis
# ---------------------------------------------------------------------------


@router.get("/{video_id}/queue-analysis", response_model=QueueAnalysisResponse)
async def get_queue_analysis(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> QueueAnalysisResponse:
    """
    Return avg/max wait times, abandonment count/rate, and high-wait periods.

    Wait time = time between BILLING_QUEUE_JOIN and next BILLING_QUEUE_ABANDON or EXIT.
    Periods where avg_wait > 300 seconds are flagged as high_wait_period.

    Requirements: 13.1, 13.2, 13.5, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:queue-analysis"

    def compute() -> QueueAnalysisResponse:
        events = _get_video_events(video_id, db)

        # Build per-visitor event timeline (exclude staff)
        visitor_events: Dict[str, list] = defaultdict(list)
        for ev in events:
            if not ev.is_staff:
                visitor_events[ev.visitor_id].append(ev)

        wait_times: List[float] = []
        abandonment_count = 0
        total_joins = 0

        for visitor_id, evs in visitor_events.items():
            # Find BILLING_QUEUE_JOIN events
            for i, ev in enumerate(evs):
                if ev.event_type != "BILLING_QUEUE_JOIN":
                    continue
                total_joins += 1
                join_ts = _ts_aware(ev.timestamp)

                # Find next BILLING_QUEUE_ABANDON or EXIT after this join
                for next_ev in evs[i + 1:]:
                    if next_ev.event_type in ("BILLING_QUEUE_ABANDON", "EXIT"):
                        wait = (_ts_aware(next_ev.timestamp) - join_ts).total_seconds()
                        wait_times.append(wait)
                        if next_ev.event_type == "BILLING_QUEUE_ABANDON":
                            abandonment_count += 1
                        break

        avg_wait = round(statistics.mean(wait_times), 2) if wait_times else 0.0
        max_wait = round(max(wait_times), 2) if wait_times else 0.0
        abandonment_rate = round(abandonment_count / total_joins, 4) if total_joins > 0 else 0.0

        # Identify high-wait periods: 15-minute windows where avg_wait > 300s
        high_wait_periods: List[HighWaitPeriod] = []
        if events:
            min_ts = _ts_aware(events[0].timestamp)
            max_ts = _ts_aware(events[-1].timestamp)
            window = timedelta(minutes=15)
            current_start = min_ts
            while current_start <= max_ts:
                current_end = current_start + window
                # Collect wait times for joins in this window
                window_waits: List[float] = []
                for visitor_id, evs in visitor_events.items():
                    for i, ev in enumerate(evs):
                        if ev.event_type != "BILLING_QUEUE_JOIN":
                            continue
                        join_ts = _ts_aware(ev.timestamp)
                        if not (current_start <= join_ts < current_end):
                            continue
                        for next_ev in evs[i + 1:]:
                            if next_ev.event_type in ("BILLING_QUEUE_ABANDON", "EXIT"):
                                window_waits.append(
                                    (_ts_aware(next_ev.timestamp) - join_ts).total_seconds()
                                )
                                break
                if window_waits and statistics.mean(window_waits) > 300:
                    high_wait_periods.append(
                        HighWaitPeriod(
                            period_start=current_start,
                            period_end=current_end,
                            avg_wait_seconds=round(statistics.mean(window_waits), 2),
                        )
                    )
                current_start = current_end

        return QueueAnalysisResponse(
            video_id=video_id,
            avg_wait_time_seconds=avg_wait,
            max_wait_time_seconds=max_wait,
            abandonment_count=abandonment_count,
            abandonment_rate=abandonment_rate,
            high_wait_periods=high_wait_periods,
        )

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return QueueAnalysisResponse.model_validate(data)
    return data


# ---------------------------------------------------------------------------
# GET /api/v1/videos/{video_id}/dwell-distribution
# ---------------------------------------------------------------------------


@router.get("/{video_id}/dwell-distribution", response_model=DwellDistributionResponse)
async def get_dwell_distribution(
    video_id: str,
    response: Response,
    current_user: Annotated[UserContext, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
) -> DwellDistributionResponse:
    """
    Return a histogram of dwell times in 30-second buckets plus summary statistics.

    Requirements: 14.1, 14.2, 14.5, 29.1, 29.2, 29.3, 29.5
    """
    video = _get_video_or_404(video_id, db)
    _check_ownership(video, current_user)

    cache_key = f"analytics:{video_id}:dwell-distribution"

    def compute() -> DwellDistributionResponse:
        dwell_events = (
            db.query(EventModel)
            .filter(
                EventModel.metadata_["video_id"].as_string() == video_id,
                EventModel.event_type == "ZONE_DWELL",
                EventModel.dwell_ms.isnot(None),
                EventModel.is_staff == False,
            )
            .all()
        )

        if not dwell_events:
            return DwellDistributionResponse(
                video_id=video_id,
                buckets=[],
                median_dwell_seconds=0.0,
                mean_dwell_seconds=0.0,
                p95_dwell_seconds=0.0,
            )

        dwell_seconds = [ev.dwell_ms / 1000.0 for ev in dwell_events]

        # Build histogram with 30-second buckets
        bucket_size = 30
        max_dwell = max(dwell_seconds)
        num_buckets = int(max_dwell // bucket_size) + 1

        bucket_counts: Dict[int, int] = defaultdict(int)
        for d in dwell_seconds:
            bucket_idx = int(d // bucket_size)
            bucket_counts[bucket_idx] += 1

        buckets: List[DwellBucket] = [
            DwellBucket(
                bucket_start_seconds=i * bucket_size,
                bucket_end_seconds=(i + 1) * bucket_size,
                count=bucket_counts.get(i, 0),
            )
            for i in range(num_buckets)
        ]

        # Summary statistics
        sorted_dwells = sorted(dwell_seconds)
        n = len(sorted_dwells)
        median_dwell = round(statistics.median(sorted_dwells), 2)
        mean_dwell = round(statistics.mean(sorted_dwells), 2)
        p95_idx = max(0, int(0.95 * n) - 1)
        p95_dwell = round(sorted_dwells[p95_idx], 2)

        return DwellDistributionResponse(
            video_id=video_id,
            buckets=buckets,
            median_dwell_seconds=median_dwell,
            mean_dwell_seconds=mean_dwell,
            p95_dwell_seconds=p95_dwell,
        )

    data, from_cache = await _get_cached_or_compute(cache_key, compute, response)
    if from_cache:
        return DwellDistributionResponse.model_validate(data)
    return data
