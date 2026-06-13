"""Tests for ``shopai engine ranking`` -- fleet-wide engine
leaderboard.

For every engine with activity in the window, compute a
fleet-wide outcome score + executed count, then rank.

Covers:

  - Empty window → friendly empty message
  - Single-engine activity bubbles up correctly
  - Multiple engines ranked by outcome_score desc
  - Engines with no polarised events fall AFTER scored engines
  - Tie-break: equal scores ordered by executed desc, then
    engine name
  - --limit caps result count
  - Queue scan failure → clean error
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
        window_hours=168, limit=20, json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _row(*, id_, engine, status):
    return {
        "id": id_,
        "engine": engine,
        "status": status,
    }


def _fake_queue(rows=None, outcomes=None, scan_raises=None):
    rows = rows or []
    outcomes = outcomes or {}
    q = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    fake_cursor = MagicMock()
    if scan_raises is not None:
        fake_conn.execute.side_effect = scan_raises
    else:
        fake_cursor.fetchall.return_value = rows
        fake_conn.execute.return_value = fake_cursor
    q._conn = fake_conn
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


# ─── Empty state ─────────────────────────────────────────────


class TestEmptyState:

    def test_no_activity_text_friendly(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, code = _capture(
                cli._cmd_engine_ranking, _ns(),
            )
        assert code == 0
        assert "No engine activity" in out

    def test_no_activity_json_envelope(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, code = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["engine_count"] == 0
        assert data["engines"] == []


# ─── Single-engine surfaces ──────────────────────────────────


class TestSingleEngine:

    def test_single_engine_surfaces(self, cli):
        rows = [
            _row(id_="x1", engine="loyalty", status="executed"),
            _row(id_="x2", engine="loyalty", status="failed"),
        ]
        outcomes = {
            "x1": [
                {"polarity": "positive",
                 "metrics": {"revenue": 50.0}},
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        assert len(data["engines"]) == 1
        e = data["engines"][0]
        assert e["engine"] == "loyalty"
        assert e["executed"] == 1
        assert e["failed"] == 1
        assert e["positive_outcomes"] == 1
        assert e["outcome_score"] == 1.0
        assert e["revenue"] == 50.0


# ─── Ranking ─────────────────────────────────────────────────


class TestRanking:

    def test_higher_outcome_score_first(self, cli):
        rows = [
            _row(id_="hi1", engine="winning", status="executed"),
            _row(id_="lo1", engine="losing", status="executed"),
        ]
        outcomes = {
            "hi1": [
                {"polarity": "positive", "metrics": {}},
            ],
            "lo1": [
                {"polarity": "negative", "metrics": {}},
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        names = [e["engine"] for e in data["engines"]]
        assert names == ["winning", "losing"]

    def test_unscored_engines_fall_after_scored(self, cli):
        """An engine with executed actions but no polarised
        outcomes should rank BELOW any engine with a score,
        regardless of executed count -- 'we have data and it's
        good' beats 'we have data but no feedback'."""
        rows = [
            # Unscored engine with many execs.
            *[_row(id_=f"u{i}", engine="unscored", status="executed")
              for i in range(10)],
            # Scored engine with single exec, score=100%.
            _row(id_="s1", engine="scored", status="executed"),
        ]
        outcomes = {
            "s1": [
                {"polarity": "positive", "metrics": {}},
            ],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        names = [e["engine"] for e in data["engines"]]
        # scored beats unscored despite unscored having 10x executions
        assert names == ["scored", "unscored"]

    def test_tie_break_by_executed_then_name(self, cli):
        """Two engines with identical scores should tie-break
        by executed count desc, then by engine name asc for
        determinism."""
        rows = [
            # Same score (100%), same executed count → name tiebreak
            _row(id_="b1", engine="bbb", status="executed"),
            _row(id_="a1", engine="aaa", status="executed"),
        ]
        outcomes = {
            "b1": [{"polarity": "positive", "metrics": {}}],
            "a1": [{"polarity": "positive", "metrics": {}}],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        names = [e["engine"] for e in data["engines"]]
        # Name asc: aaa before bbb
        assert names == ["aaa", "bbb"]


# ─── Limit ───────────────────────────────────────────────────


class TestLimit:

    def test_limit_caps_result(self, cli):
        rows = [
            _row(id_=f"x{i}", engine=f"e{i}", status="executed")
            for i in range(10)
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking,
                _ns(limit=3, json=True),
            )
        data = json.loads(out)
        # 10 engines exist but the envelope only shows 3.
        assert data["engine_count"] == 10
        assert len(data["engines"]) == 3


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_scan_failure_surfaces_clean_error(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                scan_raises=RuntimeError("db locked"),
            ),
        ):
            out, code = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        assert code == 1
        data = json.loads(out)
        assert data["status"] == "error"
        assert "db locked" in data["error"]

    def test_get_outcomes_raise_keeps_engine(self, cli):
        rows = [
            _row(id_="x", engine="loyalty", status="executed"),
        ]
        q = _fake_queue(rows=rows)
        q.get_outcomes.side_effect = RuntimeError("outcomes missing")
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, code = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["engine_count"] == 1
        e = data["engines"][0]
        assert e["engine"] == "loyalty"
        assert e["executed"] == 1
        # outcomes-raise → score stays None
        assert e["outcome_score"] is None


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=[]),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking,
                _ns(window_hours=72, limit=10, json=True),
            )
        data = json.loads(out)
        for k in (
            "window_hours", "limit", "engine_count", "engines",
        ):
            assert k in data
        assert data["window_hours"] == 72
        assert data["limit"] == 10


# ─── Quarantine flags ────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


class TestQuarantineFlags:
    """Engines on the quarantine state's exemptions / released /
    alert_paused lists get a ``flags`` list per row so operators
    can spot paused engines in the leaderboard."""

    def test_empty_flags_for_clean_engine(self, cli, data_dir):
        rows = [
            _row(id_="x1", engine="loyalty", status="executed"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        assert data["engines"][0]["flags"] == []

    def test_alert_paused_flag_surfaces(self, cli, data_dir):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        rows = [
            _row(id_="x1", engine="loyalty", status="executed"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        assert "alert_paused" in data["engines"][0]["flags"]

    def test_multiple_flags(self, cli, data_dir):
        from core.approval import quarantine
        quarantine.exempt_engine("loyalty")
        quarantine.add_alert_pause("loyalty")
        rows = [
            _row(id_="x1", engine="loyalty", status="executed"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        data = json.loads(out)
        flags = set(data["engines"][0]["flags"])
        assert "exempt" in flags
        assert "alert_paused" in flags

    def test_text_render_shows_flags_column(
        self, cli, data_dir,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        rows = [
            _row(id_="x1", engine="loyalty", status="executed"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(),
            )
        assert "FLAGS" in out
        assert "alert_paused" in out

    def test_quarantine_probe_failure_falls_back_empty(
        self, cli, data_dir,
    ):
        """If load_state raises, flags stays empty -- ranking
        still works."""
        rows = [
            _row(id_="x1", engine="loyalty", status="executed"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ), patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            out, code = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["engines"][0]["flags"] == []


class TestTopDrillDown:
    """The text view ends with a 'Top: X' highlight + a drill-
    down hint pointing the operator at `engine summary <leader>`.
    Mirrors the drill-down hint pattern already standard across
    the autonomous-loop observability stack."""

    def test_drill_down_hint_renders(self, cli):
        rows = [
            _row(id_="a1", engine="winning", status="executed"),
            _row(id_="b1", engine="losing", status="executed"),
        ]
        outcomes = {
            "a1": [{"polarity": "positive", "metrics": {}}],
            "b1": [{"polarity": "negative", "metrics": {}}],
        }
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(
                rows=rows, outcomes=outcomes,
            ),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(),
            )
        assert "Top: winning" in out
        assert "Drill down: `shopai engine summary winning`" in out

    def test_drill_down_hint_absent_in_json(self, cli):
        """JSON envelope is unchanged -- the hint is a text-
        view nicety."""
        rows = [
            _row(id_="a1", engine="winning", status="executed"),
        ]
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(rows=rows),
        ):
            out, _ = _capture(
                cli._cmd_engine_ranking, _ns(json=True),
            )
        assert "Drill down" not in out
