"""Tests for ``engine_confidence_calibration`` + CLI surface.

Engines self-assign each action a confidence in [0, 1]. The
calibration method checks whether high-confidence actions
actually produce higher positive-outcome ratios than low-
confidence ones — i.e. whether the engine's self-assessment
is meaningful.

Bucketing: half-open intervals [0.0, 0.5), [0.5, 0.6),
[0.6, 0.7), [0.7, 0.8), [0.8, 0.9), [0.9, 1.0] — the top
bucket is closed on the right so confidence=1.0 falls in it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"queue": fresh}
    fresh._conn.close()


def _seed(q, *, engine, confidence, positive, negative=0):
    for i in range(positive):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="", confidence=confidence,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={}, source_event=f"p_{engine}_{confidence}_{i}",
        )
    for i in range(negative):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="", confidence=confidence,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="refunds/create", polarity="negative",
            metrics={}, source_event=f"n_{engine}_{confidence}_{i}",
        )


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


# ─── engine_confidence_calibration() ───────────────────────────


class TestCalibrationMethod:

    def test_empty_engine_returns_empty_buckets(self, isolated_state):
        q = isolated_state["queue"]
        result = q.engine_confidence_calibration("nonexistent")
        # 6 buckets always; all empty
        assert len(result["buckets"]) == 6
        assert all(b["action_count"] == 0 for b in result["buckets"])
        assert result["monotonic_increasing"] is None

    def test_empty_string_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        result = q.engine_confidence_calibration("")
        assert result["buckets"] == []
        assert result["monotonic_increasing"] is None

    def test_bucketing_assigns_correct_ranges(self, isolated_state):
        q = isolated_state["queue"]
        _seed(q, engine="e", confidence=0.55, positive=10, negative=0)
        _seed(q, engine="e", confidence=0.75, positive=10, negative=0)
        _seed(q, engine="e", confidence=0.95, positive=10, negative=0)
        result = q.engine_confidence_calibration("e")
        by_label = {b["label"]: b for b in result["buckets"]}
        assert by_label["0.5-0.6"]["action_count"] == 10
        assert by_label["0.7-0.8"]["action_count"] == 10
        assert by_label["0.9-1.0"]["action_count"] == 10
        # Other buckets are empty
        for label in ("0.0-0.5", "0.6-0.7", "0.8-0.9"):
            assert by_label[label]["action_count"] == 0

    def test_top_bucket_includes_confidence_one(self, isolated_state):
        """confidence=1.0 belongs in the top bucket, not a phantom
        out-of-range bucket. The top edge is 1.001 internally to
        guarantee this."""
        q = isolated_state["queue"]
        _seed(q, engine="e", confidence=1.0, positive=5, negative=0)
        result = q.engine_confidence_calibration("e")
        by_label = {b["label"]: b for b in result["buckets"]}
        assert by_label["0.9-1.0"]["action_count"] == 5

    def test_well_calibrated_engine_monotonic(self, isolated_state):
        """High confidence → high outcome_score. Monotonic_increasing
        is True."""
        q = isolated_state["queue"]
        _seed(q, engine="good", confidence=0.55, positive=3, negative=7)
        _seed(q, engine="good", confidence=0.75, positive=7, negative=3)
        _seed(q, engine="good", confidence=0.95, positive=9, negative=1)
        result = q.engine_confidence_calibration("good")
        assert result["monotonic_increasing"] is True
        by_label = {b["label"]: b for b in result["buckets"]}
        assert by_label["0.5-0.6"]["outcome_score"] == 0.3
        assert by_label["0.7-0.8"]["outcome_score"] == 0.7
        assert by_label["0.9-1.0"]["outcome_score"] == 0.9

    def test_inverted_engine_flagged(self, isolated_state):
        """Mid-confidence beats high-confidence → inverted →
        monotonic_increasing is False."""
        q = isolated_state["queue"]
        _seed(q, engine="bad", confidence=0.55, positive=5, negative=5)
        _seed(q, engine="bad", confidence=0.75, positive=9, negative=1)
        _seed(q, engine="bad", confidence=0.95, positive=4, negative=6)
        result = q.engine_confidence_calibration("bad")
        assert result["monotonic_increasing"] is False

    def test_single_bucket_with_outcomes_returns_none_monotonic(
        self, isolated_state,
    ):
        """Need ≥ 2 buckets with outcome data to assess
        monotonicity. With one, return None."""
        q = isolated_state["queue"]
        _seed(q, engine="e", confidence=0.85, positive=10, negative=0)
        result = q.engine_confidence_calibration("e")
        assert result["monotonic_increasing"] is None

    def test_actions_counted_once_despite_multiple_outcomes(
        self, isolated_state,
    ):
        """An action with 3 outcomes adds 1 to action_count but 3
        to positive/negative counts (LEFT JOIN duplicate handling).
        Important: action_count is per-action, polarity counts are
        per-outcome-row."""
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="", confidence=0.95,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        for i in range(3):
            q.record_outcome(
                a.id, topic="orders/create", polarity="positive",
                metrics={}, source_event=f"multi_{i}",
            )
        result = q.engine_confidence_calibration("e")
        by_label = {b["label"]: b for b in result["buckets"]}
        top = by_label["0.9-1.0"]
        # One action, three outcomes
        assert top["action_count"] == 1
        assert top["positive_outcomes"] == 3
        assert top["negative_outcomes"] == 0

    def test_actions_without_confidence_excluded(self, isolated_state):
        """Actions with confidence=NULL aren't bucketable —
        excluded from the calibration entirely (not silently
        dropped into bucket[0])."""
        q = isolated_state["queue"]
        # No confidence
        a = q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="positive", metrics={},
            source_event="noconf",
        )
        result = q.engine_confidence_calibration("e")
        # All buckets empty — no confidence-tagged actions exist
        assert all(b["action_count"] == 0 for b in result["buckets"])

    def test_low_confidence_bucket_renders(self, isolated_state):
        """confidence < 0.5 lands in the [0.0, 0.5) bucket."""
        q = isolated_state["queue"]
        _seed(q, engine="e", confidence=0.2, positive=5, negative=5)
        result = q.engine_confidence_calibration("e")
        by_label = {b["label"]: b for b in result["buckets"]}
        assert by_label["0.0-0.5"]["action_count"] == 10

    def test_buckets_have_full_shape(self, isolated_state):
        """Each bucket has all required keys."""
        q = isolated_state["queue"]
        _seed(q, engine="e", confidence=0.95, positive=5)
        result = q.engine_confidence_calibration("e")
        for b in result["buckets"]:
            assert set(b.keys()) == {
                "label", "low", "high",
                "action_count", "positive_outcomes",
                "negative_outcomes", "outcome_score",
            }


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_unknown_engine_renders_empty(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_engine_calibration,
            argparse.Namespace(engine_name="ghost", json=False),
        )
        assert code == 0
        assert "Confidence calibration for engine: ghost" in out
        assert "no actions with recorded confidence" in out

    def test_well_calibrated_render(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, engine="good", confidence=0.55, positive=3, negative=7)
        _seed(q, engine="good", confidence=0.75, positive=7, negative=3)
        _seed(q, engine="good", confidence=0.95, positive=9, negative=1)
        out, _ = _capture(
            cli._cmd_engine_calibration,
            argparse.Namespace(engine_name="good", json=False),
        )
        assert "well-calibrated" in out
        # Table rows for non-empty buckets
        assert "0.5-0.6" in out
        assert "0.7-0.8" in out
        assert "0.9-1.0" in out

    def test_inverted_render(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, engine="bad", confidence=0.55, positive=5, negative=5)
        _seed(q, engine="bad", confidence=0.75, positive=9, negative=1)
        _seed(q, engine="bad", confidence=0.95, positive=4, negative=6)
        out, _ = _capture(
            cli._cmd_engine_calibration,
            argparse.Namespace(engine_name="bad", json=False),
        )
        assert "INVERTED" in out
        assert "confidence floor" in out  # auto-approve mention

    def test_insufficient_data_render(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, engine="lonely", confidence=0.85, positive=5)
        out, _ = _capture(
            cli._cmd_engine_calibration,
            argparse.Namespace(engine_name="lonely", json=False),
        )
        assert "insufficient data" in out

    def test_json_mode(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, engine="e", confidence=0.95, positive=5, negative=5)
        out, _ = _capture(
            cli._cmd_engine_calibration,
            argparse.Namespace(engine_name="e", json=True),
        )
        data = json.loads(out)
        assert data["engine"] == "e"
        assert "buckets" in data
        assert "monotonic_increasing" in data
        # Top bucket reflects what we seeded
        top = next(
            b for b in data["buckets"] if b["label"] == "0.9-1.0"
        )
        assert top["action_count"] == 10
        assert top["outcome_score"] == 0.5

    def test_json_first_char_is_brace(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_engine_calibration,
            argparse.Namespace(engine_name="e", json=True),
        )
        assert out.strip()[0] == "{"

    def test_queue_failure_renders_unavailable_text(
        self, cli, isolated_state,
    ):
        with patch.object(
            isolated_state["queue"],
            "engine_confidence_calibration",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_engine_calibration,
                argparse.Namespace(engine_name="e", json=False),
            )
        assert code == 0
        assert "Calibration unavailable" in out

    def test_queue_failure_renders_empty_json(
        self, cli, isolated_state,
    ):
        with patch.object(
            isolated_state["queue"],
            "engine_confidence_calibration",
            side_effect=RuntimeError("db lock"),
        ):
            out, _ = _capture(
                cli._cmd_engine_calibration,
                argparse.Namespace(engine_name="e", json=True),
            )
        data = json.loads(out)
        assert data["buckets"] == []
        assert "error" in data
