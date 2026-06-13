"""Tests for ``shopai engine compare <a> <b>`` -- head-to-head
fleet comparison of two engines.

For each engine, scan ``pending_actions`` for activity within
the window, aggregate executed/failed/pending + outcome polarity
+ revenue, then surface side-by-side with a per-metric winner.

Covers:

  - Both engine names required
  - engine_a != engine_b
  - Each engine profiled independently (separate scans)
  - outcome_score per engine = positive / (positive+negative);
    None when no polarised events
  - Winner determination: higher-is-better for executed /
    positive / outcome_score / revenue; lower-is-better for
    failed / negative; "tie" on equal values
  - JSON envelope shape
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        engine_a="loyalty",
        engine_b="cart_recovery",
        window_hours=168, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _row(*, id_, status):
    return {
        "id": id_,
        "status": status,
    }


def _fake_queue(rows_by_engine=None, outcomes=None):
    """Build a queue where ``_conn.execute`` returns rows based
    on which engine the SQL was scoped to. The handler binds
    ``engine`` as the first SQL param."""
    rows_by_engine = rows_by_engine or {}
    outcomes = outcomes or {}
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None

    def _execute(sql, params):
        engine = params[0]
        cursor = MagicMock()
        cursor.fetchall.return_value = list(
            rows_by_engine.get(engine, []),
        )
        return cursor

    fake_conn.execute.side_effect = _execute
    q._conn = fake_conn
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


# ─── Argument validation ─────────────────────────────────────


class TestArgValidation:

    def test_missing_engine_a_fails(self, cli):
        out, code = _capture(
            cli._cmd_engine_compare, _ns(engine_a=""),
        )
        assert code == 1
        assert "both engine_a and engine_b are required" in out

    def test_missing_engine_b_fails(self, cli):
        out, code = _capture(
            cli._cmd_engine_compare, _ns(engine_b=""),
        )
        assert code == 1
        assert "both engine_a and engine_b are required" in out

    def test_same_engine_fails(self, cli):
        out, code = _capture(
            cli._cmd_engine_compare,
            _ns(engine_a="loyalty", engine_b="loyalty"),
        )
        assert code == 1
        assert "must be different" in out


# ─── Per-engine profiling ────────────────────────────────────


class TestProfiling:

    def test_each_engine_profiled_independently(self, cli):
        rows = {
            "loyalty": [
                _row(id_="a1", status="executed"),
                _row(id_="a2", status="executed"),
                _row(id_="a3", status="failed"),
            ],
            "cart_recovery": [
                _row(id_="b1", status="executed"),
                _row(id_="b2", status="pending"),
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine=rows),
        ):
            out, code = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["engine_a"]["engine"] == "loyalty"
        assert data["engine_a"]["executed"] == 2
        assert data["engine_a"]["failed"] == 1
        assert data["engine_b"]["engine"] == "cart_recovery"
        assert data["engine_b"]["executed"] == 1
        assert data["engine_b"]["pending"] == 1

    def test_outcomes_rolled_only_for_executed(self, cli):
        rows = {
            "loyalty": [
                _row(id_="x1", status="executed"),
                _row(id_="x2", status="failed"),
            ],
            "cart_recovery": [],
        }
        outcomes = {
            "x1": [
                {"polarity": "positive",
                 "metrics": {"revenue": 50.0}},
            ],
            # Even though x2 has an outcome entry, it shouldn't
            # be polled (status=failed).
            "x2": [
                {"polarity": "positive",
                 "metrics": {"revenue": 9999.0}},
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows_by_engine=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        # The 9999 from x2 must NOT appear -- only x1's 50.
        assert data["engine_a"]["revenue"] == 50.0
        assert data["engine_a"]["positive_outcomes"] == 1

    def test_outcome_score_computed(self, cli):
        rows = {
            "loyalty": [_row(id_="x", status="executed")],
            "cart_recovery": [],
        }
        outcomes = {
            "x": [
                {"polarity": "positive", "metrics": {}},
                {"polarity": "positive", "metrics": {}},
                {"polarity": "negative", "metrics": {}},
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows_by_engine=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        # 2 positive / (2+1) = 0.6667
        assert data["engine_a"]["outcome_score"] == pytest.approx(
            2 / 3,
        )

    def test_outcome_score_none_when_no_polarised(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        assert data["engine_a"]["outcome_score"] is None
        assert data["engine_b"]["outcome_score"] is None


# ─── Winner determination ────────────────────────────────────


class TestWinners:

    def test_higher_executed_wins(self, cli):
        rows = {
            "loyalty": [_row(id_=f"a{i}", status="executed")
                        for i in range(5)],
            "cart_recovery": [_row(id_="b", status="executed")],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        assert data["winners"]["executed"] == "loyalty"

    def test_lower_failed_wins(self, cli):
        """Failed is the rare 'lower is better' metric."""
        rows = {
            "loyalty": [_row(id_=f"a{i}", status="failed")
                        for i in range(5)],
            "cart_recovery": [_row(id_="b", status="failed")],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        # cart_recovery had FEWER failures → wins.
        assert data["winners"]["failed"] == "cart_recovery"

    def test_equal_values_produce_tie(self, cli):
        rows = {
            "loyalty": [_row(id_="x", status="executed")],
            "cart_recovery": [_row(id_="y", status="executed")],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        assert data["winners"]["executed"] == "tie"

    def test_one_side_none_other_wins(self, cli):
        """outcome_score=None on one side; the side with real
        data wins."""
        rows = {
            "loyalty": [_row(id_="x", status="executed")],
            "cart_recovery": [],
        }
        outcomes = {
            "x": [
                {"polarity": "positive", "metrics": {}},
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows_by_engine=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(json=True),
            )
        data = json.loads(out)
        # cart_recovery has no polarised events → loyalty wins.
        assert data["winners"]["outcome_score"] == "loyalty"


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare,
                _ns(
                    engine_a="loyalty",
                    engine_b="cart_recovery",
                    window_hours=48, json=True,
                ),
            )
        data = json.loads(out)
        for k in (
            "engine_a", "engine_b", "window_hours", "winners",
        ):
            assert k in data
        assert data["window_hours"] == 48
        for side in (data["engine_a"], data["engine_b"]):
            for k in (
                "engine", "executed", "failed", "pending",
                "positive_outcomes", "negative_outcomes",
                "outcome_score", "revenue",
            ):
                assert k in side
        for k in (
            "executed", "failed", "positive_outcomes",
            "negative_outcomes", "outcome_score", "revenue",
        ):
            assert k in data["winners"]


# ─── Text mode ───────────────────────────────────────────────


class TestTextMode:

    def test_text_renders_side_by_side(self, cli):
        rows = {
            "loyalty": [
                _row(id_="x", status="executed"),
            ],
            "cart_recovery": [
                _row(id_="y", status="executed"),
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine=rows),
        ):
            out, code = _capture(
                cli._cmd_engine_compare, _ns(),
            )
        assert code == 0
        # Both engine labels appear.
        assert "loyalty" in out
        assert "cart_recovery" in out
        # Header row markers.
        assert "METRIC" in out
        assert "WINNER" in out

    def test_drill_down_hint_points_to_winner_fleet(self, cli):
        """When engine_a has more metric wins, the drill-down
        hint points at engine fleet <engine_a>."""
        rows = {
            # loyalty has more executions + positive outcomes
            "loyalty": [
                _row(id_="x1", status="executed"),
                _row(id_="x2", status="executed"),
            ],
            "cart_recovery": [],
        }
        outcomes = {
            "x1": [{"polarity": "positive", "metrics": {}}],
            "x2": [{"polarity": "positive", "metrics": {}}],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows_by_engine=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare, _ns(),
            )
        assert (
            "Drill down: `shopai engine fleet loyalty`"
            in out
        )


# ─── Quarantine flags ────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


class TestQuarantineFlags:
    """Each profile gets a ``flags`` list of quarantine state
    so operators picking between A and B see which is paused."""

    def test_both_clean_empty_flags(self, cli, data_dir):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine={}),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare,
                _ns(
                    engine_a="loyalty",
                    engine_b="cart_recovery",
                    json=True,
                ),
            )
        data = json.loads(out)
        assert data["engine_a"]["flags"] == []
        assert data["engine_b"]["flags"] == []

    def test_one_alert_paused(self, cli, data_dir):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine={}),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare,
                _ns(
                    engine_a="loyalty",
                    engine_b="cart_recovery",
                    json=True,
                ),
            )
        data = json.loads(out)
        assert data["engine_a"]["flags"] == ["alert_paused"]
        assert data["engine_b"]["flags"] == []

    def test_text_render_includes_flags_row(
        self, cli, data_dir,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine={}),
        ):
            out, _ = _capture(
                cli._cmd_engine_compare,
                _ns(
                    engine_a="loyalty",
                    engine_b="cart_recovery",
                ),
            )
        assert "flags" in out
        assert "alert_paused" in out

    def test_load_state_failure_falls_back_empty(
        self, cli, data_dir,
    ):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows_by_engine={}),
        ), patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            out, code = _capture(
                cli._cmd_engine_compare,
                _ns(
                    engine_a="loyalty",
                    engine_b="cart_recovery",
                    json=True,
                ),
            )
        assert code == 0
        data = json.loads(out)
        assert data["engine_a"]["flags"] == []
