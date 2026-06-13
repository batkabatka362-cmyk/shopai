"""Tests for ``core.approval.engine_health_history`` -- the
trajectory recorder for engine_health scores.

Mirrors the ``alert_history`` test surface:
  - record_score / record_scores append to the persisted log
  - recent_history filters by window + optional engine
  - latest_per_engine returns the newest per engine
  - clear / prune housekeeping
  - Pattern J guard short-circuits under pytest by default
  - load_raw_events is fail-open on missing / corrupt file
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.approval.engine_health_history import (
    ScoreEvent,
    _load_raw_events,
    _save_events,
    clear,
    latest_per_engine,
    prune,
    recent_history,
    record_score,
    record_scores,
)


@pytest.fixture
def isolated_data(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def no_test_guard():
    """Disable the Pattern J guard so tests can verify the
    actual recording behaviour."""
    with patch(
        "core.approval.engine_health_history."
        "_is_test_environment",
        return_value=False,
    ):
        yield


class TestRecord:

    def test_pattern_j_guard_skips_under_pytest(
        self, isolated_data,
    ):
        """Default behaviour: PYTEST_CURRENT_TEST is set, so
        record_score returns False without writing."""
        out = record_score(
            "loyalty", score=8, verdict="healthy",
        )
        assert out is False
        # No file was created
        assert not (
            isolated_data / "engine_health_history.json"
        ).exists()

    def test_appends_when_guard_lifted(
        self, isolated_data, no_test_guard,
    ):
        ok = record_score(
            "loyalty", score=7, verdict="healthy", now=1000.0,
        )
        assert ok is True
        events = _load_raw_events()
        assert len(events) == 1
        assert events[0].engine == "loyalty"
        assert events[0].score == 7
        assert events[0].verdict == "healthy"
        assert events[0].recorded_at == 1000.0

    def test_empty_engine_rejected(
        self, isolated_data, no_test_guard,
    ):
        assert record_score(
            "", score=5, verdict="warning",
        ) is False
        assert record_score(
            "   ", score=5, verdict="warning",
        ) is False
        assert _load_raw_events() == []

    def test_batch_record(
        self, isolated_data, no_test_guard,
    ):
        n = record_scores(
            [
                {"engine": "a", "score": 9, "verdict": "healthy"},
                {"engine": "b", "score": 4, "verdict": "unhealthy"},
                {"engine": "c", "score": 6, "verdict": "warning"},
            ],
            now=2000.0,
        )
        assert n == 3
        events = _load_raw_events()
        assert {e.engine for e in events} == {"a", "b", "c"}

    def test_batch_skips_malformed(
        self, isolated_data, no_test_guard,
    ):
        n = record_scores(
            [
                {"engine": "good", "score": 5, "verdict": "warning"},
                {"engine": "", "score": 5, "verdict": "warning"},
                "not-a-dict",
            ],
            now=2000.0,
        )
        # Only the well-formed entry survives. Note: passing a
        # non-dict entry via `entry.get(...)` raises AttributeError,
        # which the implementation catches and skips.
        assert n == 1


class TestRecentHistory:

    def test_window_filtering(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        # Three events: 1h, 1d, 10d ago
        record_score("loyalty", score=8, verdict="healthy",
                     now=now - 3600.0)
        record_score("loyalty", score=7, verdict="healthy",
                     now=now - 86400.0)
        record_score("loyalty", score=5, verdict="warning",
                     now=now - 86400.0 * 10.0)
        # 7-day window → 2 events
        history = recent_history(
            since_seconds=86400.0 * 7.0, now=now,
        )
        assert len(history) == 2

    def test_engine_filter(
        self, isolated_data, no_test_guard,
    ):
        record_score(
            "loyalty", score=8, verdict="healthy", now=1000.0,
        )
        record_score(
            "cart_recovery", score=5, verdict="warning",
            now=1100.0,
        )
        loyalty_only = recent_history(
            "loyalty", since_seconds=86400.0, now=1200.0,
        )
        assert len(loyalty_only) == 1
        assert loyalty_only[0].engine == "loyalty"

    def test_newest_first_ordering(
        self, isolated_data, no_test_guard,
    ):
        record_score(
            "loyalty", score=8, verdict="healthy", now=1000.0,
        )
        record_score(
            "loyalty", score=5, verdict="warning", now=2000.0,
        )
        record_score(
            "loyalty", score=3, verdict="unhealthy", now=1500.0,
        )
        history = recent_history(
            "loyalty", since_seconds=86400.0, now=2500.0,
        )
        assert [e.score for e in history] == [5, 3, 8]


class TestLatestPerEngine:

    def test_picks_newest_per_engine(
        self, isolated_data, no_test_guard,
    ):
        record_score(
            "loyalty", score=8, verdict="healthy", now=1000.0,
        )
        record_score(
            "loyalty", score=5, verdict="warning", now=2000.0,
        )
        record_score(
            "cart_recovery", score=9, verdict="healthy",
            now=1500.0,
        )
        latest = latest_per_engine(
            since_seconds=86400.0, now=2500.0,
        )
        assert latest["loyalty"].score == 5
        assert latest["cart_recovery"].score == 9

    def test_window_excludes_old(
        self, isolated_data, no_test_guard,
    ):
        record_score(
            "loyalty", score=8, verdict="healthy", now=1000.0,
        )
        # 31 days later -> outside the 30-day default window
        latest = latest_per_engine(
            since_seconds=86400.0 * 30.0,
            now=1000.0 + 86400.0 * 31.0,
        )
        assert "loyalty" not in latest


class TestHousekeeping:

    def test_clear_wipes_file(
        self, isolated_data, no_test_guard,
    ):
        record_score(
            "loyalty", score=8, verdict="healthy",
        )
        assert _load_raw_events()  # non-empty
        clear()
        assert _load_raw_events() == []

    def test_clear_when_no_file(self, isolated_data):
        # No file present yet -- clear should not crash
        clear()
        assert _load_raw_events() == []

    def test_prune_drops_old(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        record_score(
            "old_engine", score=8, verdict="healthy",
            now=now - 86400.0 * 100.0,
        )
        record_score(
            "fresh", score=5, verdict="warning",
            now=now - 86400.0 * 10.0,
        )
        dropped = prune(
            older_than_seconds=86400.0 * 30.0, now=now,
        )
        assert dropped == 1
        remaining = _load_raw_events()
        assert len(remaining) == 1
        assert remaining[0].engine == "fresh"

    def test_prune_noop_when_nothing_old(
        self, isolated_data, no_test_guard,
    ):
        record_score("loyalty", score=8, verdict="healthy")
        dropped = prune(
            older_than_seconds=86400.0 * 90.0,
        )
        assert dropped == 0


class TestLoadRawEvents:

    def test_fails_open_on_missing_file(self, isolated_data):
        assert _load_raw_events() == []

    def test_fails_open_on_corrupt_file(
        self, isolated_data,
    ):
        (
            isolated_data / "engine_health_history.json"
        ).write_text("not json {{{")
        assert _load_raw_events() == []

    def test_skips_non_list_payload(self, isolated_data):
        (
            isolated_data / "engine_health_history.json"
        ).write_text('{"wrong": "shape"}')
        assert _load_raw_events() == []

    def test_skips_malformed_entries(self, isolated_data):
        # Mix of well-formed + malformed
        payload = [
            {
                "engine": "loyalty",
                "recorded_at": 1000.0,
                "score": 8,
                "verdict": "healthy",
            },
            "not-a-dict",
            {"engine": "broken", "recorded_at": "abc"},
        ]
        (
            isolated_data / "engine_health_history.json"
        ).write_text(json.dumps(payload))
        events = _load_raw_events()
        # Only the well-formed entry survives
        engines = {e.engine for e in events}
        assert "loyalty" in engines


class TestPersistence:

    def test_round_trip(
        self, isolated_data, no_test_guard,
    ):
        record_score(
            "loyalty", score=7, verdict="healthy", now=1000.0,
        )
        # Re-read via raw API
        path = isolated_data / "engine_health_history.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw[0]["engine"] == "loyalty"
        assert raw[0]["score"] == 7
        assert raw[0]["verdict"] == "healthy"
        assert raw[0]["recorded_at"] == 1000.0

    def test_save_events_is_atomic(self, isolated_data):
        """_save_events should write via temp + rename so no
        partial file is observable mid-write."""
        events = [
            ScoreEvent(
                engine="loyalty",
                recorded_at=time.time(),
                score=8,
                verdict="healthy",
            ),
        ]
        _save_events(events)
        # Tmp file should NOT exist after a successful write
        tmp = (
            isolated_data / "engine_health_history.json.tmp"
        )
        assert not tmp.exists()
        # Real file exists with content
        assert (
            isolated_data / "engine_health_history.json"
        ).exists()


# --- Regression detector --------------------------------------


from core.approval.engine_health_history import (  # noqa: E402
    HealthRegression,
    find_regressions,
)


class TestFindRegressions:

    def _seed(
        self, *, engine: str = "loyalty",
        baseline_score: int = 9, baseline_count: int = 5,
        latest_score: int = 4, now: float = 1_000_000.0,
    ):
        """Seed N baseline events then one fresh latest event."""
        day = 86400.0
        for i in range(baseline_count):
            record_score(
                engine,
                score=baseline_score,
                verdict="healthy",
                now=now - day * (i + 2),
            )
        record_score(
            engine,
            score=latest_score,
            verdict=(
                "unhealthy" if latest_score < 5
                else "warning" if latest_score < 8
                else "healthy"
            ),
            now=now - 1800.0,
        )

    def test_no_history_returns_empty(self, isolated_data):
        assert find_regressions() == []

    def test_drop_above_threshold_flagged(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed(
            baseline_score=9, latest_score=4, now=now,
        )
        regressions = find_regressions(now=now)
        assert len(regressions) == 1
        r = regressions[0]
        assert r.engine == "loyalty"
        assert r.latest_score == 4
        assert r.baseline_score == 9.0
        assert r.drop == 5.0

    def test_drop_below_threshold_not_flagged(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed(
            baseline_score=9, latest_score=7, now=now,
        )
        # drop=2 < default min_drop=3
        assert find_regressions(now=now) == []

    def test_insufficient_baseline_skipped(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed(
            baseline_score=9, latest_score=2,
            baseline_count=2, now=now,
        )
        # baseline_count=2 < default min_baseline_samples=3
        assert find_regressions(now=now) == []

    def test_no_latest_event_skipped(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        day = 86400.0
        for i in range(5):
            record_score(
                "loyalty", score=9, verdict="healthy",
                now=now - day * (i + 2),
            )
        # No event in latest window -> skipped
        assert find_regressions(now=now) == []

    def test_ranks_by_drop_size_desc(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        # loyalty: drop 5
        self._seed(
            engine="loyalty", baseline_score=9, latest_score=4,
            now=now,
        )
        # cart_recovery: drop 4
        self._seed(
            engine="cart_recovery",
            baseline_score=10, latest_score=6, now=now,
        )
        regressions = find_regressions(now=now)
        assert [r.engine for r in regressions] == [
            "loyalty", "cart_recovery",
        ]

    def test_custom_min_drop(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed(
            baseline_score=9, latest_score=7, now=now,
        )
        regressions = find_regressions(
            min_drop=1.0, now=now,
        )
        assert len(regressions) == 1
        assert regressions[0].drop == 2.0

    def test_median_excludes_latest_event(
        self, isolated_data, no_test_guard,
    ):
        """Baseline median is computed from events OLDER than
        the latest window, so the latest event doesn't skew its
        own baseline."""
        now = 1_000_000.0
        day = 86400.0
        for i in range(3):
            record_score(
                "loyalty", score=10, verdict="healthy",
                now=now - day * (i + 2),
            )
        record_score(
            "loyalty", score=5, verdict="warning",
            now=now - 1800.0,
        )
        regressions = find_regressions(now=now)
        assert len(regressions) == 1
        assert regressions[0].baseline_score == 10.0
        assert regressions[0].drop == 5.0

    def test_regression_dataclass_shape(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed(
            baseline_score=9, latest_score=4, now=now,
        )
        r = find_regressions(now=now)[0]
        assert isinstance(r, HealthRegression)
        assert r.samples_in_baseline == 5
        assert r.latest_verdict == "unhealthy"


from core.approval.engine_health_history import (  # noqa: E402
    ChronicWarning,
    find_chronic_warnings,
)


class TestFindChronicWarnings:
    """A chronic warning is a STATE (consistently sick),
    distinct from a regression which is a CHANGE."""

    def _seed_consistent(
        self, engine, scores, now,
    ):
        """Seed N events at the given scores spread across
        the last week."""
        day = 86400.0
        for i, s in enumerate(scores):
            record_score(
                engine,
                score=s,
                verdict=(
                    "unhealthy" if s < 5
                    else "warning" if s < 8
                    else "healthy"
                ),
                now=now - day * (i + 0.5),
            )

    def test_no_history_returns_empty(self, isolated_data):
        assert find_chronic_warnings() == []

    def test_all_warning_flagged(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed_consistent(
            "loyalty", [6, 5, 6, 5, 6], now=now,
        )
        warnings = find_chronic_warnings(now=now)
        assert len(warnings) == 1
        w = warnings[0]
        assert isinstance(w, ChronicWarning)
        assert w.engine == "loyalty"
        assert w.latest_score == 6
        assert w.samples == 5
        # avg of 5,5,6,6,6 = 5.6
        assert w.avg_score == pytest.approx(5.6, abs=0.01)

    def test_any_healthy_in_window_excludes(
        self, isolated_data, no_test_guard,
    ):
        """If even one sample was healthy (>=7), it's not
        chronic -- the engine recovered at least once."""
        now = 1_000_000.0
        self._seed_consistent(
            "loyalty", [6, 5, 8, 5, 6], now=now,
        )
        warnings = find_chronic_warnings(now=now)
        assert warnings == []

    def test_insufficient_samples_skipped(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed_consistent("loyalty", [6, 5], now=now)
        # Default min_samples=3
        assert find_chronic_warnings(now=now) == []
        # With min_samples=2 it qualifies
        warnings = find_chronic_warnings(
            now=now, min_samples=2,
        )
        assert len(warnings) == 1

    def test_sorted_sickest_first(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        self._seed_consistent("warn_a", [6, 6, 6], now=now)
        self._seed_consistent(
            "sick_b", [3, 3, 3], now=now,
        )
        warnings = find_chronic_warnings(now=now)
        assert [w.engine for w in warnings] == [
            "sick_b", "warn_a",
        ]
        # Lowest score first
        assert warnings[0].latest_score == 3
        assert warnings[1].latest_score == 6

    def test_old_samples_excluded(
        self, isolated_data, no_test_guard,
    ):
        now = 1_000_000.0
        # Seed 3 stale warnings (8 days ago) -- outside the
        # default 7d window.
        day = 86400.0
        for i in range(3):
            record_score(
                "loyalty", score=5, verdict="warning",
                now=now - day * (8 + i),
            )
        warnings = find_chronic_warnings(now=now)
        assert warnings == []

    def test_custom_floor(
        self, isolated_data, no_test_guard,
    ):
        """Operators can tighten the floor -- e.g.,
        treat score=8 as warning."""
        now = 1_000_000.0
        self._seed_consistent(
            "loyalty", [7, 7, 7], now=now,
        )
        # Default floor=7 means score 7 is healthy -> not
        # chronic.
        assert find_chronic_warnings(now=now) == []
        # Floor=8 means score 7 is below healthy.
        warnings = find_chronic_warnings(
            now=now, healthy_score_floor=8,
        )
        assert len(warnings) == 1
