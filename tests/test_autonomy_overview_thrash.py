"""Tests for autonomy_overview_thrash (Wave 904)."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.automation.autonomy_overview import OverviewSnapshot
from core.automation.autonomy_overview_history import (
    record_snapshot,
)
from core.automation.autonomy_overview_thrash import (
    ThrashBucket,
    ThrashReport,
    compute_thrash,
    latest_thrash_verdict,
)


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch(
        "core.automation.autonomy_overview_history."
        "_is_test_environment",
        return_value=False,
    ):
        yield


def _seed(path, verdict, captured_at, store_id=None):
    s = OverviewSnapshot()
    s.captured_at = captured_at
    s.store_id = store_id
    # Build a snapshot whose verdict computes to the asked
    # state without relying on _VERDICT_EMOJI internals.
    if verdict == "degraded":
        s.alerts_critical = 1
        s.armed_total = 1
    elif verdict == "active":
        s.armed_total = 1
        s.fires_invoked = 1
    elif verdict == "armed":
        s.armed_total = 1
    # idle = defaults
    assert s.verdict == verdict, (
        f"seed bug: expected {verdict} got {s.verdict}"
    )
    record_snapshot(s, path=path)


def _patch_history(path):
    from core.automation import autonomy_overview_history
    return patch.object(
        autonomy_overview_history, "_DEFAULT_PATH", path,
    )


class TestThrashBucket:

    def test_calm_label(self):
        assert ThrashBucket(
            start_at=0, end_at=1, flip_count=0,
        ).density_label == "calm"

    def test_elevated_label(self):
        assert ThrashBucket(
            start_at=0, end_at=1, flip_count=3,
        ).density_label == "elevated"

    def test_thrashing_label(self):
        assert ThrashBucket(
            start_at=0, end_at=1, flip_count=10,
        ).density_label == "thrashing"


class TestThrashReportVerdict:

    def test_no_buckets_calm(self):
        assert ThrashReport().verdict == "calm"

    def test_below_threshold_calm(self):
        r = ThrashReport()
        r.buckets = [
            ThrashBucket(0, 1, 1), ThrashBucket(1, 2, 2),
        ]
        assert r.verdict == "calm"

    def test_peak_elevated(self):
        r = ThrashReport()
        r.buckets = [
            ThrashBucket(0, 1, 0), ThrashBucket(1, 2, 3),
        ]
        assert r.verdict == "elevated"

    def test_peak_thrashing(self):
        r = ThrashReport()
        r.buckets = [
            ThrashBucket(0, 1, 1), ThrashBucket(1, 2, 7),
        ]
        assert r.verdict == "thrashing"


class TestComputeThrash:

    def test_empty_history(self, tmp_path):
        p = tmp_path / "h.json"
        with _patch_history(p):
            r = compute_thrash()
        assert r.total_flips == 0
        assert r.verdict == "calm"

    def test_no_flips_steady_state(self, tmp_path):
        p = tmp_path / "h.json"
        now = time.time()
        for i in range(5):
            _seed(p, "idle", now - 300 + i * 60)
        with _patch_history(p):
            r = compute_thrash(window_hours=1.0)
        assert r.total_flips == 0

    def test_one_flip(self, tmp_path):
        p = tmp_path / "h.json"
        now = time.time()
        _seed(p, "idle", now - 600)
        _seed(p, "armed", now - 300)
        with _patch_history(p):
            r = compute_thrash(
                window_hours=1.0, bucket_hours=1.0,
            )
        assert r.total_flips == 1

    def test_thrashing_pattern(self, tmp_path):
        p = tmp_path / "h.json"
        now = time.time()
        # 6 verdict flips within last hour -> thrashing
        verdicts = [
            "idle", "armed", "idle", "armed",
            "idle", "armed", "idle",
        ]
        for i, v in enumerate(verdicts):
            _seed(p, v, now - 3000 + i * 400)
        with _patch_history(p):
            r = compute_thrash(
                window_hours=1.0, bucket_hours=1.0,
            )
        assert r.peak_flips >= 5
        assert r.verdict == "thrashing"

    def test_store_filter(self, tmp_path):
        p = tmp_path / "h.json"
        now = time.time()
        _seed(p, "idle", now - 600, store_id="a")
        _seed(p, "armed", now - 500, store_id="a")
        _seed(p, "idle", now - 400, store_id="b")
        with _patch_history(p):
            r = compute_thrash(
                window_hours=1.0, store_id="a",
            )
        assert r.store_id == "a"
        assert r.total_flips == 1


class TestLatestThrashVerdict:

    def test_empty(self, tmp_path):
        p = tmp_path / "h.json"
        with _patch_history(p):
            assert latest_thrash_verdict() == "calm"


class TestCrossStorePollutionFix:
    """W937 bugfix: fleet-wide call must NOT manufacture flips
    at store boundaries."""

    def test_fleet_call_does_not_inflate_cross_store_flips(
        self, tmp_path,
    ):
        p = tmp_path / "h.json"
        now = time.time()
        # Store A: 3 consecutive idle snapshots
        for i in range(3):
            _seed(p, "idle", now - 1800 + i * 60,
                  store_id="store-a")
        # Store B: 3 consecutive armed snapshots
        for i in range(3):
            _seed(p, "armed", now - 1500 + i * 60,
                  store_id="store-b")
        # Fleet-wide call -- bug would count idle->armed flip
        # at store boundary. With fix: 0 flips per store.
        with _patch_history(p):
            r = compute_thrash(window_hours=1.0)
        assert r.total_flips == 0, (
            f"fleet-wide call manufactured {r.total_flips} "
            "phantom flip(s) at store boundary"
        )

    def test_per_store_flip_still_detected(self, tmp_path):
        p = tmp_path / "h.json"
        now = time.time()
        # Store A: 4 verdict flips
        verdicts = ["idle", "armed", "idle", "armed", "idle"]
        for i, v in enumerate(verdicts):
            _seed(p, v, now - 1500 + i * 60,
                  store_id="store-a")
        # Store B: 0 flips
        for i in range(2):
            _seed(p, "idle", now - 1500 + i * 60,
                  store_id="store-b")
        with _patch_history(p):
            r = compute_thrash(window_hours=1.0)
        # 4 real flips from store A; none manufactured
        assert r.total_flips == 4


class TestTruncatedBucketFix:
    """W937 bugfix: window_hours=1.5 / bucket_hours=1.0 must
    cover the full 1.5h tail, not silently truncate."""

    def test_fractional_window_covers_full_range(
        self, tmp_path,
    ):
        p = tmp_path / "h.json"
        now = time.time()
        # Entry 70 min ago (would be dropped pre-fix when
        # n_buckets = int(1.5) = 1, covering only last 60min).
        _seed(p, "idle", now - 70 * 60)
        _seed(p, "armed", now - 30 * 60)
        with _patch_history(p):
            r = compute_thrash(
                window_hours=1.5, bucket_hours=1.0,
            )
        # 2 buckets now cover [-2h, -1h) and [-1h, 0); both
        # entries fit, 1 flip detected.
        assert r.total_flips == 1
        assert len(r.buckets) == 2
