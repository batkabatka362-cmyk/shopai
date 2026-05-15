"""Tests for ``engine_scorecard`` + CLI surface.

The capstone view consolidating every per-engine signal into
one operator glance: volume + outcomes + calibration + workflow
+ veto + revenue + governance.
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
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"queue": fresh}
    fresh._conn.close()


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
    defaults = dict(engine_name="cart_recovery", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── engine_scorecard() shape ──────────────────────────────────


class TestScorecardShape:

    def test_unknown_engine_returns_full_empty_shape(
        self, isolated_state,
    ):
        """Even when the engine has no history, the scorecard
        returns the full schema so downstream callers can
        rely on it."""
        q = isolated_state["queue"]
        sc = q.engine_scorecard("ghost")
        assert sc["engine"] == "ghost"
        assert set(sc.keys()) >= {
            "engine", "volume", "outcomes", "calibration",
            "workflow", "veto", "revenue",
        }
        # All counts default to 0
        assert all(v == 0 for v in sc["volume"].values())
        assert sc["outcomes"]["total_outcomes"] == 0
        assert sc["calibration"]["monotonic_increasing"] is None
        assert sc["workflow"]["pending"]["pending_count"] == 0
        assert sc["workflow"]["decision"]["decided_count"] == 0
        assert sc["veto"]["decided_count"] == 0
        assert sc["revenue"]["gross_revenue"] == 0.0

    def test_empty_string_engine_returns_error(self, isolated_state):
        q = isolated_state["queue"]
        sc = q.engine_scorecard("")
        assert sc.get("error") == "invalid_engine_name"

    def test_volume_counts_per_status(self, isolated_state):
        q = isolated_state["queue"]
        # 3 pending + 2 rejected + 4 executed
        for i in range(3):
            q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
        for i in range(2):
            a = q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
            q.reject(a.id, decided_by="op")
        for i in range(4):
            a = q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
            q.approve(a.id, decided_by="op")
            q.attach_result(a.id, success=True, result={})
        sc = q.engine_scorecard("e")
        assert sc["volume"]["pending"] == 3
        assert sc["volume"]["rejected"] == 2
        assert sc["volume"]["executed"] == 4


class TestScorecardComposition:

    def test_pulls_outcomes_from_engine_outcome_stats(
        self, isolated_state,
    ):
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="positive",
            metrics={"revenue": 100}, source_event="p1",
        )
        sc = q.engine_scorecard("e")
        assert sc["outcomes"]["positive_count"] == 1
        assert sc["outcomes"]["total_outcomes"] == 1

    def test_pulls_revenue_from_revenue_attribution(
        self, isolated_state,
    ):
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="positive",
            metrics={"revenue": 250}, source_event="p1",
        )
        sc = q.engine_scorecard("e")
        assert sc["revenue"]["gross_revenue"] == 250.0
        assert sc["revenue"]["net_revenue"] == 250.0

    def test_pulls_veto_from_rejection_rate(
        self, isolated_state,
    ):
        q = isolated_state["queue"]
        # 4 approved + 6 rejected → rate 0.6
        for _ in range(4):
            a = q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
            q.approve(a.id, decided_by="op")
        for _ in range(6):
            a = q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
            q.reject(a.id, decided_by="op")
        sc = q.engine_scorecard("e")
        assert sc["veto"]["decided_count"] == 10
        assert sc["veto"]["rejected_count"] == 6
        assert sc["veto"]["rejection_rate"] == 0.6

    def test_workflow_subsection_has_both_panels(
        self, isolated_state,
    ):
        """workflow.pending + workflow.decision are both present
        even when the engine has only one (callers rely on the
        schema)."""
        q = isolated_state["queue"]
        # Only pending — no decisions yet
        q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="",
        )
        sc = q.engine_scorecard("e")
        assert "pending" in sc["workflow"]
        assert "decision" in sc["workflow"]
        assert sc["workflow"]["pending"]["pending_count"] == 1
        assert sc["workflow"]["decision"]["decided_count"] == 0


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_unknown_engine_renders_empty_shape(
        self, cli, isolated_state,
    ):
        out, code = _capture(
            cli._cmd_engine_scorecard, _ns(engine_name="ghost"),
        )
        assert code == 0
        assert "Scorecard: ghost" in out
        # Empty-state messages for each section
        assert "(no matched outcomes" in out
        assert "(none)" in out  # pending
        assert "(no decisions yet)" in out

    def test_full_scorecard_renders_all_sections(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="", confidence=0.9,
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="o", polarity="positive",
            metrics={"revenue": 50}, source_event="p1",
        )
        out, _ = _capture(
            cli._cmd_engine_scorecard, _ns(engine_name="e"),
        )
        # All section headers present
        assert "Volume:" in out
        assert "Outcomes:" in out
        assert "Calibration:" in out
        assert "Workflow:" in out
        assert "Veto:" in out
        assert "Revenue:" in out
        assert "Governance:" in out

    def test_governance_reflects_allowlist(
        self, cli, isolated_state,
    ):
        from core.approval.auto_approve import enable_engine
        enable_engine("trusted")
        out, _ = _capture(
            cli._cmd_engine_scorecard,
            _ns(engine_name="trusted"),
        )
        # auto-approve: yes appears
        assert "auto-approve: yes" in out

    def test_governance_reflects_exempt(self, cli, isolated_state):
        from core.approval.quarantine import exempt_engine
        exempt_engine("returns_engine")
        out, _ = _capture(
            cli._cmd_engine_scorecard,
            _ns(engine_name="returns_engine"),
        )
        assert "quarantine-exempt: yes" in out

    def test_alert_when_auto_approved_and_inverted(
        self, cli, isolated_state,
    ):
        """The capstone alert: an engine that's auto-approved
        AND has inverted calibration. Same signal as PR #167's
        engines-calibration sweep, surfaced for a single engine."""
        from core.approval.auto_approve import enable_engine
        q = isolated_state["queue"]

        def _seed(conf, pos, neg):
            for i in range(pos):
                a = q.enqueue(
                    engine="bad", action_type="y", capability="z",
                    params={}, narrative="", confidence=conf,
                )
                q.approve(a.id, decided_by="op")
                q.attach_result(a.id, success=True, result={})
                q.record_outcome(
                    a.id, topic="o", polarity="positive",
                    metrics={}, source_event=f"p_{conf}_{i}",
                )
            for i in range(neg):
                a = q.enqueue(
                    engine="bad", action_type="y", capability="z",
                    params={}, narrative="", confidence=conf,
                )
                q.approve(a.id, decided_by="op")
                q.attach_result(a.id, success=True, result={})
                q.record_outcome(
                    a.id, topic="o", polarity="negative",
                    metrics={}, source_event=f"n_{conf}_{i}",
                )

        # Inverted shape: mid-confidence beats high-confidence
        _seed(0.55, 5, 5)
        _seed(0.75, 9, 1)
        _seed(0.95, 4, 6)
        enable_engine("bad")
        out, _ = _capture(
            cli._cmd_engine_scorecard, _ns(engine_name="bad"),
        )
        # Both individual signals + the headline alert
        assert "INVERTED" in out
        assert "auto-approve: yes" in out
        assert "ALERT" in out

    def test_no_alert_when_not_auto_approved(
        self, cli, isolated_state,
    ):
        """Inverted but not allowlisted → no ALERT banner
        (it's a warning, not a high-priority action)."""
        q = isolated_state["queue"]
        # Seed inverted shape without enabling auto-approve
        for conf, pos, neg in [
            (0.55, 5, 5), (0.75, 9, 1), (0.95, 4, 6),
        ]:
            for i in range(pos):
                a = q.enqueue(
                    engine="bad", action_type="y", capability="z",
                    params={}, narrative="", confidence=conf,
                )
                q.approve(a.id, decided_by="op")
                q.attach_result(a.id, success=True, result={})
                q.record_outcome(
                    a.id, topic="o", polarity="positive",
                    metrics={}, source_event=f"p_{conf}_{i}",
                )
            for i in range(neg):
                a = q.enqueue(
                    engine="bad", action_type="y", capability="z",
                    params={}, narrative="", confidence=conf,
                )
                q.approve(a.id, decided_by="op")
                q.attach_result(a.id, success=True, result={})
                q.record_outcome(
                    a.id, topic="o", polarity="negative",
                    metrics={}, source_event=f"n_{conf}_{i}",
                )
        out, _ = _capture(
            cli._cmd_engine_scorecard, _ns(engine_name="bad"),
        )
        assert "INVERTED" in out
        assert "ALERT" not in out

    def test_json_mode(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_engine_scorecard,
            _ns(engine_name="ghost", json=True),
        )
        data = json.loads(out)
        # Schema present even on empty
        assert data["engine"] == "ghost"
        assert set(data.keys()) >= {
            "engine", "volume", "outcomes", "calibration",
            "workflow", "veto", "revenue", "governance",
        }

    def test_json_first_char_is_brace(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_engine_scorecard,
            _ns(engine_name="ghost", json=True),
        )
        assert out.strip()[0] == "{"

    def test_queue_failure_renders_text_unavailable(
        self, cli, isolated_state,
    ):
        with patch.object(
            isolated_state["queue"], "engine_scorecard",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_engine_scorecard, _ns(engine_name="e"),
            )
        assert code == 0
        assert "Scorecard unavailable" in out

    def test_queue_failure_renders_json_error(
        self, cli, isolated_state,
    ):
        with patch.object(
            isolated_state["queue"], "engine_scorecard",
            side_effect=RuntimeError("db lock"),
        ):
            out, _ = _capture(
                cli._cmd_engine_scorecard,
                _ns(engine_name="e", json=True),
            )
        data = json.loads(out)
        assert "error" in data


class TestResilience:

    def test_auto_approve_module_failure(
        self, cli, isolated_state,
    ):
        """Allowlist probe failing treats it as empty rather
        than crashing the whole scorecard."""
        with patch(
            "core.approval.auto_approve.load_config",
            side_effect=RuntimeError("config broken"),
        ):
            out, _ = _capture(
                cli._cmd_engine_scorecard,
                _ns(engine_name="e"),
            )
        # Renders cleanly with auto-approve: no
        assert "auto-approve: no" in out

    def test_quarantine_state_failure(self, cli, isolated_state):
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("state broken"),
        ):
            out, _ = _capture(
                cli._cmd_engine_scorecard,
                _ns(engine_name="e"),
            )
        # Renders cleanly with both quarantine flags = no
        assert "quarantine-exempt: no" in out
        assert "manually-released: no" in out
