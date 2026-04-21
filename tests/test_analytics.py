import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _ts_aware(ts):
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _make_event(visitor_id, event_type, timestamp, zone_id=None, dwell_ms=None, is_staff=False):
    ev = MagicMock()
    ev.visitor_id = visitor_id
    ev.event_type = event_type
    ev.timestamp = timestamp
    ev.zone_id = zone_id
    ev.dwell_ms = dwell_ms
    ev.is_staff = is_staff
    return ev


BASE_TS = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Journey computation (mirrors analytics_routes.py compute() logic)
# ---------------------------------------------------------------------------

def _compute_journey(events):
    visitor_events = defaultdict(list)
    for ev in sorted(events, key=lambda e: _ts_aware(e.timestamp)):
        visitor_events[ev.visitor_id].append(ev)

    result = {}
    for visitor_id, evs in visitor_events.items():
        transitions = []
        open_entries = {}

        for ev in evs:
            if ev.event_type == "ZONE_ENTER":
                open_entries[ev.zone_id] = ev
            elif ev.event_type == "ZONE_EXIT":
                entry_ev = open_entries.pop(ev.zone_id, None)
                entry_ts = entry_ev.timestamp if entry_ev else None
                dwell = None
                if entry_ts is not None:
                    dwell = round(
                        (_ts_aware(ev.timestamp) - _ts_aware(entry_ts)).total_seconds(), 2
                    )
                transitions.append({
                    "zone_id": ev.zone_id,
                    "entry_timestamp": entry_ts,
                    "exit_timestamp": ev.timestamp,
                    "dwell_time_seconds": dwell,
                })
            elif ev.event_type == "ZONE_DWELL":
                if ev.zone_id not in open_entries:
                    dwell_s = (ev.dwell_ms / 1000.0) if ev.dwell_ms else None
                    transitions.append({
                        "zone_id": ev.zone_id,
                        "entry_timestamp": ev.timestamp,
                        "exit_timestamp": None,
                        "dwell_time_seconds": dwell_s,
                    })

        for zone_id, entry_ev in open_entries.items():
            transitions.append({
                "zone_id": zone_id,
                "entry_timestamp": entry_ev.timestamp,
                "exit_timestamp": None,
                "dwell_time_seconds": None,
            })

        transitions.sort(
            key=lambda t: _ts_aware(t["entry_timestamp"])
            if t["entry_timestamp"]
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        result[visitor_id] = transitions

    return result


class TestJourneyOrdering:
    def test_transitions_ordered_chronologically(self):
        events = [
            _make_event("VIS_aaa", "ZONE_ENTER", BASE_TS + timedelta(minutes=5), zone_id="ZONE_B"),
            _make_event("VIS_aaa", "ZONE_EXIT",  BASE_TS + timedelta(minutes=8), zone_id="ZONE_B"),
            _make_event("VIS_aaa", "ZONE_ENTER", BASE_TS + timedelta(minutes=1), zone_id="ZONE_A"),
            _make_event("VIS_aaa", "ZONE_EXIT",  BASE_TS + timedelta(minutes=4), zone_id="ZONE_A"),
        ]
        journey = _compute_journey(events)
        transitions = journey["VIS_aaa"]
        assert len(transitions) == 2
        assert transitions[0]["zone_id"] == "ZONE_A"
        assert transitions[1]["zone_id"] == "ZONE_B"

    def test_dwell_time_calculated_from_enter_exit(self):
        enter_ts = BASE_TS
        exit_ts  = BASE_TS + timedelta(seconds=90)
        events = [
            _make_event("VIS_bbb", "ZONE_ENTER", enter_ts, zone_id="ZONE_A"),
            _make_event("VIS_bbb", "ZONE_EXIT",  exit_ts,  zone_id="ZONE_A"),
        ]
        journey = _compute_journey(events)
        t = journey["VIS_bbb"][0]
        assert t["dwell_time_seconds"] == 90.0

    def test_zone_dwell_event_used_when_no_open_entry(self):
        events = [
            _make_event("VIS_ccc", "ZONE_DWELL", BASE_TS, zone_id="ZONE_A", dwell_ms=45000),
        ]
        journey = _compute_journey(events)
        t = journey["VIS_ccc"][0]
        assert t["dwell_time_seconds"] == 45.0

    def test_open_entry_without_exit_has_none_dwell(self):
        events = [
            _make_event("VIS_ddd", "ZONE_ENTER", BASE_TS, zone_id="ZONE_A"),
        ]
        journey = _compute_journey(events)
        t = journey["VIS_ddd"][0]
        assert t["dwell_time_seconds"] is None
        assert t["exit_timestamp"] is None

    def test_multiple_visitors_independent(self):
        events = [
            _make_event("VIS_e01", "ZONE_ENTER", BASE_TS,                        zone_id="ZONE_A"),
            _make_event("VIS_e01", "ZONE_EXIT",  BASE_TS + timedelta(seconds=30), zone_id="ZONE_A"),
            _make_event("VIS_e02", "ZONE_ENTER", BASE_TS + timedelta(seconds=5),  zone_id="ZONE_B"),
            _make_event("VIS_e02", "ZONE_EXIT",  BASE_TS + timedelta(seconds=60), zone_id="ZONE_B"),
        ]
        journey = _compute_journey(events)
        assert journey["VIS_e01"][0]["dwell_time_seconds"] == 30.0
        assert journey["VIS_e02"][0]["dwell_time_seconds"] == 55.0

    def test_empty_events_returns_empty(self):
        assert _compute_journey([]) == {}


# ---------------------------------------------------------------------------
# Peak-hours computation (mirrors analytics_routes.py compute() logic)
# ---------------------------------------------------------------------------

def _compute_peak_hours(events):
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: _ts_aware(e.timestamp))
    min_ts = _ts_aware(sorted_events[0].timestamp)
    max_ts = _ts_aware(sorted_events[-1].timestamp)

    interval_delta = timedelta(minutes=15)
    interval_data = []

    current_start = min_ts
    while current_start <= max_ts:
        current_end = current_start + interval_delta
        interval_events = [
            ev for ev in sorted_events
            if _ts_aware(ev.timestamp) >= current_start
            and _ts_aware(ev.timestamp) < current_end
        ]
        unique_visitors = len({
            ev.visitor_id for ev in interval_events
            if ev.event_type == "ENTRY" and not ev.is_staff
        })
        interval_data.append({
            "interval_start": current_start,
            "unique_visitors": unique_visitors,
        })
        current_start = current_end

    sorted_by_traffic = sorted(interval_data, key=lambda x: x["unique_visitors"], reverse=True)
    peak_starts = {d["interval_start"] for d in sorted_by_traffic[:3]}

    return [
        {**d, "is_peak": d["interval_start"] in peak_starts}
        for d in interval_data
    ]


class TestPeakHoursFlagging:
    def _entry(self, visitor_id, ts):
        return _make_event(visitor_id, "ENTRY", ts)

    def test_top_3_intervals_flagged_as_peak(self):
        # Build 4 intervals with 5, 10, 3, 1 unique visitors respectively
        events = []
        for i in range(5):
            events.append(self._entry("VIS_a{:04d}".format(i), BASE_TS + timedelta(minutes=i)))
        for i in range(10):
            events.append(self._entry("VIS_b{:04d}".format(i), BASE_TS + timedelta(minutes=15 + i)))
        for i in range(3):
            events.append(self._entry("VIS_c{:04d}".format(i), BASE_TS + timedelta(minutes=30 + i)))
        for i in range(1):
            events.append(self._entry("VIS_d{:04d}".format(i), BASE_TS + timedelta(minutes=45 + i)))

        intervals = _compute_peak_hours(events)
        peak_intervals = [iv for iv in intervals if iv["is_peak"]]
        assert len(peak_intervals) == 3

        peak_counts = sorted([iv["unique_visitors"] for iv in peak_intervals], reverse=True)
        all_counts  = sorted([iv["unique_visitors"] for iv in intervals], reverse=True)
        assert peak_counts == all_counts[:3]

    def test_fewer_than_3_intervals_all_flagged(self):
        events = [self._entry("VIS_000001", BASE_TS)]
        intervals = _compute_peak_hours(events)
        assert all(iv["is_peak"] for iv in intervals)

    def test_staff_excluded_from_peak_count(self):
        events = [
            _make_event("VIS_000001", "ENTRY", BASE_TS, is_staff=True),
            _make_event("VIS_000002", "ENTRY", BASE_TS, is_staff=False),
        ]
        intervals = _compute_peak_hours(events)
        assert intervals[0]["unique_visitors"] == 1

    def test_empty_events_returns_empty(self):
        assert _compute_peak_hours([]) == []

    def test_exactly_3_intervals_all_peak(self):
        events = []
        for i in range(3):
            events.append(self._entry("VIS_{:06d}".format(i), BASE_TS + timedelta(minutes=15 * i)))
        intervals = _compute_peak_hours(events)
        assert all(iv["is_peak"] for iv in intervals)


# ---------------------------------------------------------------------------
# Zone performance_score computation (mirrors analytics_routes.py logic)
# ---------------------------------------------------------------------------

def _compute_zone_performance(zone_metrics):
    """
    performance_score = conversion_rate * 50 + (avg_dwell / max_dwell) * 50
    clamped to [0, 100].
    """
    if not zone_metrics:
        return []

    dwell_vals = [z["avg_dwell_seconds"] for z in zone_metrics]
    max_dwell = max(dwell_vals) if dwell_vals else 1.0
    if max_dwell == 0:
        max_dwell = 1.0

    result = []
    for z in zone_metrics:
        norm_dwell = z["avg_dwell_seconds"] / max_dwell
        perf = z["conversion_rate"] * 50.0 + norm_dwell * 50.0
        perf = round(max(0.0, min(100.0, perf)), 2)
        result.append({**z, "performance_score": perf})

    return sorted(result, key=lambda z: z["performance_score"], reverse=True)


class TestZonePerformanceScore:
    def test_perfect_conversion_and_max_dwell_gives_100(self):
        zones = [
            {"zone_id": "A", "conversion_rate": 1.0, "avg_dwell_seconds": 120.0, "visit_count": 10},
        ]
        result = _compute_zone_performance(zones)
        assert result[0]["performance_score"] == 100.0

    def test_zero_conversion_zero_dwell_gives_0(self):
        zones = [
            {"zone_id": "A", "conversion_rate": 0.0, "avg_dwell_seconds": 0.0, "visit_count": 5},
            {"zone_id": "B", "conversion_rate": 0.5, "avg_dwell_seconds": 60.0, "visit_count": 5},
        ]
        result = _compute_zone_performance(zones)
        zone_a = next(z for z in result if z["zone_id"] == "A")
        assert zone_a["performance_score"] == 0.0

    def test_score_clamped_between_0_and_100(self):
        zones = [
            {"zone_id": "A", "conversion_rate": 0.5, "avg_dwell_seconds": 60.0, "visit_count": 5},
            {"zone_id": "B", "conversion_rate": 0.8, "avg_dwell_seconds": 30.0, "visit_count": 3},
        ]
        result = _compute_zone_performance(zones)
        for z in result:
            assert 0.0 <= z["performance_score"] <= 100.0

    def test_zones_sorted_by_performance_score_descending(self):
        zones = [
            {"zone_id": "LOW",  "conversion_rate": 0.1, "avg_dwell_seconds": 10.0, "visit_count": 5},
            {"zone_id": "HIGH", "conversion_rate": 0.9, "avg_dwell_seconds": 90.0, "visit_count": 5},
            {"zone_id": "MID",  "conversion_rate": 0.5, "avg_dwell_seconds": 50.0, "visit_count": 5},
        ]
        result = _compute_zone_performance(zones)
        scores = [z["performance_score"] for z in result]
        assert scores == sorted(scores, reverse=True)

    def test_formula_weights_conversion_and_dwell_equally(self):
        # Zone A: conversion=1.0, dwell=0 (norm=0) -> score = 50
        # Zone B: conversion=0.0, dwell=max (norm=1) -> score = 50
        zones = [
            {"zone_id": "A", "conversion_rate": 1.0, "avg_dwell_seconds": 0.0,   "visit_count": 5},
            {"zone_id": "B", "conversion_rate": 0.0, "avg_dwell_seconds": 100.0, "visit_count": 5},
        ]
        result = _compute_zone_performance(zones)
        for z in result:
            assert z["performance_score"] == 50.0

    def test_empty_zones_returns_empty(self):
        assert _compute_zone_performance([]) == []


# ---------------------------------------------------------------------------
# Queue analysis computation (mirrors analytics_routes.py logic)
# ---------------------------------------------------------------------------

def _compute_queue_analysis(events):
    visitor_events = defaultdict(list)
    for ev in sorted(events, key=lambda e: _ts_aware(e.timestamp)):
        if not ev.is_staff:
            visitor_events[ev.visitor_id].append(ev)

    wait_times = []
    abandonment_count = 0
    total_joins = 0

    for visitor_id, evs in visitor_events.items():
        for i, ev in enumerate(evs):
            if ev.event_type != "BILLING_QUEUE_JOIN":
                continue
            total_joins += 1
            join_ts = _ts_aware(ev.timestamp)
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

    high_wait_periods = []
    if events:
        sorted_events = sorted(events, key=lambda e: _ts_aware(e.timestamp))
        min_ts = _ts_aware(sorted_events[0].timestamp)
        max_ts = _ts_aware(sorted_events[-1].timestamp)
        window = timedelta(minutes=15)
        current_start = min_ts
        while current_start <= max_ts:
            current_end = current_start + window
            window_waits = []
            for vid, evs in visitor_events.items():
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
                high_wait_periods.append({
                    "period_start": current_start,
                    "period_end": current_end,
                    "avg_wait_seconds": round(statistics.mean(window_waits), 2),
                })
            current_start = current_end

    return {
        "avg_wait_time_seconds": avg_wait,
        "max_wait_time_seconds": max_wait,
        "abandonment_count": abandonment_count,
        "abandonment_rate": abandonment_rate,
        "high_wait_periods": high_wait_periods,
    }


class TestQueueAnalysis:
    def test_abandonment_detected(self):
        events = [
            _make_event("VIS_001", "BILLING_QUEUE_JOIN",    BASE_TS),
            _make_event("VIS_001", "BILLING_QUEUE_ABANDON", BASE_TS + timedelta(seconds=120)),
        ]
        result = _compute_queue_analysis(events)
        assert result["abandonment_count"] == 1
        assert result["abandonment_rate"] == 1.0

    def test_exit_not_counted_as_abandonment(self):
        events = [
            _make_event("VIS_002", "BILLING_QUEUE_JOIN", BASE_TS),
            _make_event("VIS_002", "EXIT",               BASE_TS + timedelta(seconds=60)),
        ]
        result = _compute_queue_analysis(events)
        assert result["abandonment_count"] == 0
        assert result["abandonment_rate"] == 0.0

    def test_wait_time_calculated_correctly(self):
        events = [
            _make_event("VIS_003", "BILLING_QUEUE_JOIN", BASE_TS),
            _make_event("VIS_003", "EXIT",               BASE_TS + timedelta(seconds=200)),
        ]
        result = _compute_queue_analysis(events)
        assert result["avg_wait_time_seconds"] == 200.0
        assert result["max_wait_time_seconds"] == 200.0

    def test_high_wait_period_flagged_when_avg_over_5_min(self):
        events = [
            _make_event("VIS_004", "BILLING_QUEUE_JOIN", BASE_TS),
            _make_event("VIS_004", "EXIT",               BASE_TS + timedelta(seconds=400)),
        ]
        result = _compute_queue_analysis(events)
        assert len(result["high_wait_periods"]) == 1
        assert result["high_wait_periods"][0]["avg_wait_seconds"] == 400.0

    def test_no_high_wait_period_when_avg_under_5_min(self):
        events = [
            _make_event("VIS_005", "BILLING_QUEUE_JOIN", BASE_TS),
            _make_event("VIS_005", "EXIT",               BASE_TS + timedelta(seconds=100)),
        ]
        result = _compute_queue_analysis(events)
        assert result["high_wait_periods"] == []

    def test_staff_excluded_from_queue_analysis(self):
        events = [
            _make_event("VIS_006", "BILLING_QUEUE_JOIN",    BASE_TS,                        is_staff=True),
            _make_event("VIS_006", "BILLING_QUEUE_ABANDON", BASE_TS + timedelta(seconds=60), is_staff=True),
        ]
        result = _compute_queue_analysis(events)
        assert result["abandonment_count"] == 0
        assert result["avg_wait_time_seconds"] == 0.0

    def test_abandonment_rate_multiple_visitors(self):
        events = [
            _make_event("VIS_007", "BILLING_QUEUE_JOIN",    BASE_TS),
            _make_event("VIS_007", "BILLING_QUEUE_ABANDON", BASE_TS + timedelta(seconds=60)),
            _make_event("VIS_008", "BILLING_QUEUE_JOIN",    BASE_TS + timedelta(seconds=5)),
            _make_event("VIS_008", "EXIT",                  BASE_TS + timedelta(seconds=120)),
        ]
        result = _compute_queue_analysis(events)
        assert result["abandonment_count"] == 1
        assert result["abandonment_rate"] == 0.5

    def test_no_events_returns_zeros(self):
        result = _compute_queue_analysis([])
        assert result["avg_wait_time_seconds"] == 0.0
        assert result["abandonment_count"] == 0
        assert result["abandonment_rate"] == 0.0


# ---------------------------------------------------------------------------
# Dwell distribution computation (mirrors analytics_routes.py logic)
# ---------------------------------------------------------------------------

def _compute_dwell_distribution(dwell_seconds_list):
    if not dwell_seconds_list:
        return {
            "buckets": [],
            "median_dwell_seconds": 0.0,
            "mean_dwell_seconds": 0.0,
            "p95_dwell_seconds": 0.0,
        }

    bucket_size = 30
    max_dwell = max(dwell_seconds_list)
    num_buckets = int(max_dwell // bucket_size) + 1

    bucket_counts = defaultdict(int)
    for d in dwell_seconds_list:
        bucket_idx = int(d // bucket_size)
        bucket_counts[bucket_idx] += 1

    buckets = [
        {
            "bucket_start_seconds": i * bucket_size,
            "bucket_end_seconds": (i + 1) * bucket_size,
            "count": bucket_counts.get(i, 0),
        }
        for i in range(num_buckets)
    ]

    sorted_dwells = sorted(dwell_seconds_list)
    n = len(sorted_dwells)
    median_dwell = round(statistics.median(sorted_dwells), 2)
    mean_dwell   = round(statistics.mean(sorted_dwells), 2)
    p95_idx      = max(0, int(0.95 * n) - 1)
    p95_dwell    = round(sorted_dwells[p95_idx], 2)

    return {
        "buckets": buckets,
        "median_dwell_seconds": median_dwell,
        "mean_dwell_seconds": mean_dwell,
        "p95_dwell_seconds": p95_dwell,
    }


class TestDwellDistribution:
    def test_values_bucketed_into_30s_intervals(self):
        # 10s -> bucket 0 (0-30), 45s -> bucket 1 (30-60), 75s -> bucket 2 (60-90)
        result = _compute_dwell_distribution([10.0, 45.0, 75.0])
        assert result["buckets"][0]["count"] == 1
        assert result["buckets"][1]["count"] == 1
        assert result["buckets"][2]["count"] == 1

    def test_bucket_boundaries_correct(self):
        result = _compute_dwell_distribution([10.0, 45.0])
        assert result["buckets"][0]["bucket_start_seconds"] == 0
        assert result["buckets"][0]["bucket_end_seconds"]   == 30
        assert result["buckets"][1]["bucket_start_seconds"] == 30
        assert result["buckets"][1]["bucket_end_seconds"]   == 60

    def test_median_calculated_correctly(self):
        result = _compute_dwell_distribution([10.0, 20.0, 30.0])
        assert result["median_dwell_seconds"] == 20.0

    def test_mean_calculated_correctly(self):
        result = _compute_dwell_distribution([10.0, 20.0, 30.0])
        assert result["mean_dwell_seconds"] == 20.0

    def test_p95_calculated_correctly(self):
        # 20 values 1..20; p95_idx = max(0, int(0.95*20)-1) = 18 -> sorted[18] = 19
        values = [float(v) for v in range(1, 21)]
        result = _compute_dwell_distribution(values)
        sorted_vals = sorted(values)
        expected_p95 = sorted_vals[max(0, int(0.95 * 20) - 1)]
        assert result["p95_dwell_seconds"] == round(expected_p95, 2)

    def test_all_values_in_same_bucket(self):
        result = _compute_dwell_distribution([5.0, 10.0, 15.0, 25.0])
        assert len(result["buckets"]) == 1
        assert result["buckets"][0]["count"] == 4

    def test_empty_input_returns_zeros(self):
        result = _compute_dwell_distribution([])
        assert result["buckets"] == []
        assert result["median_dwell_seconds"] == 0.0
        assert result["mean_dwell_seconds"]   == 0.0
        assert result["p95_dwell_seconds"]    == 0.0

    def test_single_value_statistics_equal_value(self):
        result = _compute_dwell_distribution([42.0])
        assert result["p95_dwell_seconds"]    == 42.0
        assert result["median_dwell_seconds"] == 42.0
        assert result["mean_dwell_seconds"]   == 42.0
