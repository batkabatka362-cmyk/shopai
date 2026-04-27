"""Tests for ``execution.promotion_tracker.PromotionTracker``.

Coverage:
  1. Schema bootstrap on a fresh DB; unknown action_types start
     at SIMULATE.
  2. Promotion ladder — N successes at SIMULATE → DRY_RUN → LIVE.
  3. Failure path — any failure resets to SIMULATE regardless of
     prior streak.
  4. ``promoted`` flag in the snapshot is True only on the call
     that actually advanced the tier.
  5. ``snapshot()`` reflects every recorded action_type.
  6. Threshold tunable per instance.
  7. Empty / blank action_type is a no-op.
  8. ``_min_tier`` helper picks the more cautious tier.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tracker(tmp_path: Path):
    from execution.promotion_tracker import PromotionTracker

    t = PromotionTracker(
        db_path=tmp_path / "promo.db", promote_threshold=3,
    )
    yield t
    t._conn.close()


# ─── current_tier defaults ──────────────────────────────────────


class TestDefaultTier:

    def test_unknown_action_starts_simulate(self, tracker):
        assert tracker.current_tier("never_seen") == "simulate"

    def test_empty_action_type_returns_simulate(self, tracker):
        assert tracker.current_tier("") == "simulate"


# ─── promotion ladder ──────────────────────────────────────────


class TestPromotionLadder:

    def test_three_successes_promote_simulate_to_dry_run(self, tracker):
        for _ in range(2):
            out = tracker.record_success("update_price")
            assert out["promoted"] is False
            assert out["tier"] == "simulate"

        out = tracker.record_success("update_price")
        assert out["promoted"] is True
        assert out["tier"] == "dry_run"
        # Counter resets on transition so the next 3 successes
        # earn LIVE.
        assert out["consecutive_ok"] == 0

    def test_six_successes_reach_live(self, tracker):
        for _ in range(5):
            tracker.record_success("update_price")
        out = tracker.record_success("update_price")
        assert out["tier"] == "live"
        assert out["promoted"] is True
        assert tracker.current_tier("update_price") == "live"

    def test_live_does_not_promote_further(self, tracker):
        for _ in range(6):
            tracker.record_success("update_price")
        # 7th and beyond — tier stays LIVE; promoted is False
        # because nothing changed (top of ladder).
        for _ in range(3):
            out = tracker.record_success("update_price")
            assert out["tier"] == "live"
            assert out["promoted"] is False

    def test_per_action_independence(self, tracker):
        for _ in range(3):
            tracker.record_success("update_price")
        # update_price hit dry_run; create_product still simulate.
        assert tracker.current_tier("update_price") == "dry_run"
        assert tracker.current_tier("create_product") == "simulate"

    def test_threshold_tunable_per_instance(self, tmp_path: Path):
        from execution.promotion_tracker import PromotionTracker

        t = PromotionTracker(
            db_path=tmp_path / "promo.db", promote_threshold=1,
        )
        try:
            out = t.record_success("alert")
            assert out["promoted"] is True
            assert out["tier"] == "dry_run"
        finally:
            t._conn.close()


# ─── failure path ──────────────────────────────────────────────


class TestFailureDemotion:

    def test_failure_at_simulate_stays_simulate(self, tracker):
        out = tracker.record_failure("update_price")
        assert out["tier"] == "simulate"
        assert out["consecutive_ok"] == 0
        assert out["promoted"] is False

    def test_failure_after_promotion_demotes_to_simulate(self, tracker):
        # Climb to dry_run.
        for _ in range(3):
            tracker.record_success("update_price")
        assert tracker.current_tier("update_price") == "dry_run"

        # One failure resets the ladder.
        out = tracker.record_failure("update_price")
        assert out["tier"] == "simulate"
        assert out["consecutive_ok"] == 0

    def test_failure_at_live_demotes_all_the_way_down(self, tracker):
        for _ in range(6):
            tracker.record_success("update_price")
        assert tracker.current_tier("update_price") == "live"

        tracker.record_failure("update_price")
        assert tracker.current_tier("update_price") == "simulate"


# ─── snapshot ──────────────────────────────────────────────────


class TestSnapshot:

    def test_snapshot_lists_every_seen_action(self, tracker):
        tracker.record_success("update_price")
        tracker.record_success("create_product")
        tracker.record_failure("bulk_update")

        snap = tracker.snapshot()
        types = {row["action_type"] for row in snap}
        assert types == {"update_price", "create_product", "bulk_update"}

    def test_snapshot_reflects_outcomes(self, tracker):
        tracker.record_success("update_price")
        snap = tracker.snapshot()
        entry = next(r for r in snap if r["action_type"] == "update_price")
        assert entry["last_outcome"] == "success"
        assert entry["consecutive_ok"] == 1
        assert entry["current_tier"] == "simulate"


# ─── _min_tier helper ─────────────────────────────────────────


class TestMinTier:

    @pytest.mark.parametrize("a, b, expected", [
        ("simulate", "live", "simulate"),
        ("dry_run", "live", "dry_run"),
        ("live", "dry_run", "dry_run"),
        ("dry_run", "dry_run", "dry_run"),
        ("live", "live", "live"),
        # Unknown label collapses to simulate (rank 0).
        ("foo", "live", "foo"),
    ])
    def test_picks_more_conservative(self, a, b, expected):
        from execution.smart_executor import _min_tier
        assert _min_tier(a, b) == expected
