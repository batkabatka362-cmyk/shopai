"""Tests for engines._revenue_quarantine."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines._attribution_snapshot import AttributionSnapshot
from engines._revenue_quarantine import (
    compute_engine_streaks,
    is_enabled,
    maybe_auto_quarantine_from_revenue,
    threshold_cycles,
)


def _snap(
    *,
    sid: str,
    captured_at: float,
    per_engine: list[dict] | None = None,
    store_id: str | None = None,
) -> AttributionSnapshot:
    return AttributionSnapshot(
        snapshot_id=sid,
        captured_at=captured_at,
        window_hours=168.0,
        store_id=store_id,
        per_engine=per_engine or [],
    )


class TestEnvGate:

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", raising=False,
        )
        assert is_enabled() is False

    def test_on_with_env(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", "1",
        )
        assert is_enabled() is True

    def test_threshold_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_REVENUE_QUARANTINE_CYCLES", raising=False,
        )
        assert threshold_cycles() == 3

    def test_threshold_custom(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_REVENUE_QUARANTINE_CYCLES", "5",
        )
        assert threshold_cycles() == 5

    def test_threshold_floor_is_2(self, monkeypatch):
        """1 doesn't make sense for a consecutive-cycles
        threshold."""
        monkeypatch.setenv(
            "SHOPAI_REVENUE_QUARANTINE_CYCLES", "1",
        )
        assert threshold_cycles() == 2


class TestComputeStreaks:

    def test_empty_when_no_snapshots(self):
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[],
        ):
            assert compute_engine_streaks() == {}

    def test_empty_when_one_snapshot(self):
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[_snap(sid="a", captured_at=1.0)],
        ):
            assert compute_engine_streaks() == {}

    def test_single_cycle_alert_yields_streak_of_one(self):
        """Two snapshots, one regression alert -> streak=1."""
        prior = _snap(
            sid="prior", captured_at=1.0,
            per_engine=[
                {"engine": "loyalty",
                 "cluster": "retention",
                 "attributed_revenue": 1000.0,
                 "attributed_orders": 10},
            ],
        )
        latest = _snap(
            sid="latest", captured_at=2.0,
            per_engine=[
                {"engine": "loyalty",
                 "cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        # recent_snapshots returns newest-first
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[latest, prior],
        ):
            streaks = compute_engine_streaks()
        assert streaks == {"loyalty": 1}

    def test_consecutive_alerts_increment_streak(self):
        """Three snapshots, loyalty alerts in BOTH cycle-pair
        deltas -> streak=2."""
        s_oldest = _snap(
            sid="s_oldest", captured_at=1.0,
            per_engine=[
                {"engine": "loyalty", "cluster": "retention",
                 "attributed_revenue": 1000.0, "attributed_orders": 10},
            ],
        )
        s_mid = _snap(
            sid="s_mid", captured_at=2.0,
            per_engine=[
                {"engine": "loyalty", "cluster": "retention",
                 "attributed_revenue": 500.0, "attributed_orders": 5},
            ],
        )
        s_new = _snap(
            sid="s_new", captured_at=3.0,
            per_engine=[
                {"engine": "loyalty", "cluster": "retention",
                 "attributed_revenue": 100.0, "attributed_orders": 3},
            ],
        )
        # newest-first
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[s_new, s_mid, s_oldest],
        ):
            streaks = compute_engine_streaks()
        # Two cycle-pairs (new-mid, mid-oldest); loyalty
        # regressed in BOTH -> streak=2
        assert streaks["loyalty"] == 2

    def test_streak_breaks_when_engine_recovers(self):
        """If loyalty alerted in cycle N-2 but not N-1, the
        most-recent-cycle alert isn't a continuation."""
        s_oldest = _snap(
            sid="s_oldest", captured_at=1.0,
            per_engine=[
                {"engine": "loyalty", "cluster": "retention",
                 "attributed_revenue": 1000.0, "attributed_orders": 10},
            ],
        )
        s_mid = _snap(
            sid="s_mid", captured_at=2.0,
            per_engine=[
                {"engine": "loyalty", "cluster": "retention",
                 "attributed_revenue": 1100.0, "attributed_orders": 11},
            ],
        )
        s_new = _snap(
            sid="s_new", captured_at=3.0,
            per_engine=[
                {"engine": "loyalty", "cluster": "retention",
                 "attributed_revenue": 100.0, "attributed_orders": 3},
            ],
        )
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[s_new, s_mid, s_oldest],
        ):
            streaks = compute_engine_streaks()
        # New-mid: loyalty went 1100 -> 100, alert.
        # Mid-oldest: loyalty went 1000 -> 1100, NO alert.
        # Streak count = 1 (only the most-recent cycle).
        assert streaks.get("loyalty", 0) == 1


class TestMaybeAutoQuarantine:

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", raising=False,
        )
        assert maybe_auto_quarantine_from_revenue() == []

    def test_suppressed_under_pytest(self, monkeypatch):
        """Pattern J: even when enabled, returns [] under
        pytest (PYTEST_CURRENT_TEST env auto-set)."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", "1",
        )
        # PYTEST_CURRENT_TEST is set automatically
        assert maybe_auto_quarantine_from_revenue() == []

    def test_below_threshold_not_paused(self, monkeypatch):
        """Streak of 1 below default threshold of 3 -- no pause."""
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", "1",
        )
        # Manually lift the Pattern J guard
        with patch(
            "engines._revenue_quarantine._is_test_environment",
            return_value=False,
        ), patch(
            "engines._revenue_quarantine.compute_engine_streaks",
            return_value={"loyalty": 1},
        ):
            paused = maybe_auto_quarantine_from_revenue()
        assert paused == []

    def test_pauses_engine_at_threshold(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", "1",
        )
        from core.approval import quarantine
        from core.approval.quarantine import QuarantineState
        calls: list = []
        empty_state = QuarantineState(
            exemptions=frozenset(),
            released=frozenset(),
            alert_paused=frozenset(),
        )
        with patch(
            "engines._revenue_quarantine._is_test_environment",
            return_value=False,
        ), patch(
            "engines._revenue_quarantine.compute_engine_streaks",
            return_value={"loyalty": 3, "fine_engine": 1},
        ), patch.object(
            quarantine, "load_state", return_value=empty_state,
        ), patch.object(
            quarantine, "add_alert_pause",
            side_effect=lambda engine, store_id=None: calls.append(
                (engine, store_id),
            ),
        ):
            paused = maybe_auto_quarantine_from_revenue()
        assert paused == ["loyalty"]
        assert calls == [("loyalty", None)]

    def test_already_paused_engine_not_repaused(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE", "1",
        )
        from core.approval import quarantine
        from core.approval.quarantine import QuarantineState
        state_with_pause = QuarantineState(
            exemptions=frozenset(),
            released=frozenset(),
            alert_paused=frozenset([("loyalty", None)]),
        )
        with patch(
            "engines._revenue_quarantine._is_test_environment",
            return_value=False,
        ), patch(
            "engines._revenue_quarantine.compute_engine_streaks",
            return_value={"loyalty": 5},
        ), patch.object(
            quarantine, "load_state",
            return_value=state_with_pause,
        ), patch.object(
            quarantine, "add_alert_pause",
        ) as mock_add:
            paused = maybe_auto_quarantine_from_revenue()
        assert paused == []
        mock_add.assert_not_called()
