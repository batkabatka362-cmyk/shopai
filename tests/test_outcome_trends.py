"""Tests for ``core.approval.outcome_trends`` — engine
outcome-score degradation detector extracted from
``shopai engine alerts``.

This module is the data-producing core that the CLI handler
(and future daily-brief + world-model surfaces) consumes.
Tests mirror the CLI's behavioral guarantees:

  - Recent window included in baseline (subset semantics)
  - Insufficient signal below min_recent skips alerts
  - Threshold gate (only drops past threshold trigger)
  - Largest-drop-first ranking
  - Frozen EngineAlert dataclass
  - Validation: baseline must exceed recent
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from core.approval.outcome_trends import (
    EngineAlert,
    compute_engine_alerts,
)


# ─── Test queue fakes ────────────────────────────────────────


def _fake_queue(*, rows=None, outcomes=None):
    """Build a queue with ``_conn.execute()`` returning rows
    and ``get_outcomes(action_id)`` returning per-action lists."""
    rows = rows or []
    outcomes = outcomes or {}
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    fake_conn.execute.return_value = cursor
    q._conn = fake_conn
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


def _row(*, id_, engine, decided_at):
    return {"id": id_, "engine": engine, "decided_at": decided_at}


# ─── Argument validation ─────────────────────────────────────


class TestArgValidation:

    def test_baseline_must_exceed_recent(self):
        q = _fake_queue()
        with pytest.raises(ValueError, match="must exceed"):
            compute_engine_alerts(
                q, recent_hours=48, baseline_hours=48,
            )

    def test_baseline_below_recent_rejected(self):
        q = _fake_queue()
        with pytest.raises(ValueError, match="must exceed"):
            compute_engine_alerts(
                q, recent_hours=72, baseline_hours=48,
            )


# ─── Empty + no-signal ───────────────────────────────────────


class TestEmptyState:

    def test_no_rows_returns_empty_list(self):
        q = _fake_queue(rows=[])
        result = compute_engine_alerts(q)
        assert result == []

    def test_below_min_recent_polarised_not_alerted(self):
        """Recent window has only 2 polarised events (below
        default ``min_recent=3``). Even with a 100% drop, no
        alert -- the recent signal is too noisy."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = (
            [_row(id_=f"r{i}", engine="loyalty",
                  decided_at=recent_ts) for i in range(2)]
            + [_row(id_=f"o{i}", engine="loyalty",
                    decided_at=old_ts) for i in range(10)]
        )
        outcomes = {
            "r0": [{"polarity": "negative", "metrics": {}}],
            "r1": [{"polarity": "negative", "metrics": {}}],
        }
        for i in range(10):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_engine_alerts(q)
        assert result == []


# ─── Threshold gate ──────────────────────────────────────────


class TestThresholdGate:

    def test_dramatic_drop_above_threshold_alerts(self):
        """Recent: 4 neg → score 0. Baseline: 4 neg + 8 pos →
        score 0.67. Drop 0.67, threshold 0.2 → alert."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = (
            [_row(id_=f"r{i}", engine="loyalty",
                  decided_at=recent_ts) for i in range(4)]
            + [_row(id_=f"o{i}", engine="loyalty",
                    decided_at=old_ts) for i in range(8)]
        )
        outcomes = {}
        for i in range(4):
            outcomes[f"r{i}"] = [
                {"polarity": "negative", "metrics": {}},
            ]
        for i in range(8):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_engine_alerts(q)
        assert len(result) == 1
        a = result[0]
        assert isinstance(a, EngineAlert)
        assert a.engine == "loyalty"
        assert a.recent_score == 0.0
        assert a.baseline_score == pytest.approx(8 / 12)
        assert a.drop == pytest.approx(8 / 12)

    def test_below_threshold_no_alert(self):
        """Recent 2/3 pos = 0.67. Baseline 8/9 pos = 0.89.
        Drop 0.22; threshold 0.3 → no alert."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = (
            [_row(id_=f"r{i}", engine="loyalty",
                  decided_at=recent_ts) for i in range(3)]
            + [_row(id_=f"o{i}", engine="loyalty",
                    decided_at=old_ts) for i in range(6)]
        )
        outcomes = {
            "r0": [{"polarity": "positive", "metrics": {}}],
            "r1": [{"polarity": "positive", "metrics": {}}],
            "r2": [{"polarity": "negative", "metrics": {}}],
        }
        for i in range(6):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_engine_alerts(q, threshold=0.3)
        assert result == []


# ─── Ranking ─────────────────────────────────────────────────


class TestRanking:

    def test_largest_drop_first(self):
        """Two engines flagged; ranking is by drop magnitude
        regardless of activity volume."""
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = []
        outcomes = {}
        # engineA: full neg recent, full pos baseline
        for i in range(4):
            rows.append(_row(
                id_=f"a_r{i}", engine="engineA",
                decided_at=recent_ts,
            ))
            outcomes[f"a_r{i}"] = [
                {"polarity": "negative", "metrics": {}},
            ]
        for i in range(8):
            rows.append(_row(
                id_=f"a_o{i}", engine="engineA",
                decided_at=old_ts,
            ))
            outcomes[f"a_o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        # engineB: 2 pos + 2 neg recent; full pos older
        for i in range(4):
            rows.append(_row(
                id_=f"b_r{i}", engine="engineB",
                decided_at=recent_ts,
            ))
            outcomes[f"b_r{i}"] = [{
                "polarity": "positive" if i < 2 else "negative",
                "metrics": {},
            }]
        for i in range(8):
            rows.append(_row(
                id_=f"b_o{i}", engine="engineB",
                decided_at=old_ts,
            ))
            outcomes[f"b_o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_engine_alerts(q)
        assert len(result) == 2
        # engineA (~0.67 drop) before engineB (~0.33 drop)
        assert result[0].engine == "engineA"
        assert result[1].engine == "engineB"
        assert result[0].drop > result[1].drop


# ─── EngineAlert interface ───────────────────────────────────


class TestEngineAlertInterface:

    def test_is_frozen(self):
        """Frozen dataclass — callers can't accidentally mutate
        the detection result."""
        now = time.time()
        rows = [_row(id_="x", engine="e", decided_at=now - 3600.0)]
        for i in range(2, 5):
            rows.append(_row(
                id_=f"r{i}", engine="e", decided_at=now - 3600.0,
            ))
        for i in range(8):
            rows.append(_row(
                id_=f"o{i}", engine="e",
                decided_at=now - 100 * 3600.0,
            ))
        outcomes = {}
        for r in rows[:4]:
            outcomes[r["id"]] = [
                {"polarity": "negative", "metrics": {}},
            ]
        for r in rows[4:]:
            outcomes[r["id"]] = [
                {"polarity": "positive", "metrics": {}},
            ]
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_engine_alerts(q)
        assert len(result) == 1
        a = result[0]
        with pytest.raises(Exception):
            a.engine = "modified"  # type: ignore[misc]

    def test_detail_string_is_pct_formatted(self):
        now = time.time()
        recent_ts = now - 3600.0
        old_ts = now - 100 * 3600.0
        rows = (
            [_row(id_=f"r{i}", engine="loyalty",
                  decided_at=recent_ts) for i in range(4)]
            + [_row(id_=f"o{i}", engine="loyalty",
                    decided_at=old_ts) for i in range(8)]
        )
        outcomes = {}
        for i in range(4):
            outcomes[f"r{i}"] = [
                {"polarity": "negative", "metrics": {}},
            ]
        for i in range(8):
            outcomes[f"o{i}"] = [
                {"polarity": "positive", "metrics": {}},
            ]
        q = _fake_queue(rows=rows, outcomes=outcomes)
        result = compute_engine_alerts(q)
        assert "%" in result[0].detail
        assert "recent" in result[0].detail
        assert "baseline" in result[0].detail
