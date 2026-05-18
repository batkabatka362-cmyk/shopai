"""Tests for ``shopai engine summary <engine>`` -- single-engine
drilldown that combines queue counts + recent activity + outcome
rollup into one operator surface.

Covers:

  - Counts pulled from stats_by_engine()
  - Outcomes pulled from engine_outcome_stats()
  - Recent activity sourced from list_by_status (EXECUTED + FAILED)
  - --recent-n caps the listing
  - --json envelope shape
  - Zero-activity engine renders cleanly
  - Resilience: queue probe failure surfaces a clean error
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
    defaults = dict(engine_name="loyalty", recent_n=5, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_action(
    *, id_="a1", action_type="mint_loyalty_code",
    capability="SHOPIFY_CREATE_DISCOUNT",
    status_value="executed",
    decided_at=None, error=None,
):
    """Build a fake ApprovalAction with the fields the summary reads."""
    a = MagicMock()
    a.id = id_
    a.action_type = action_type
    a.capability = capability
    a.status = MagicMock(value=status_value)
    a.decided_at = decided_at if decided_at is not None else time.time() - 60
    a.decided_by = "system"
    a.result = {"error": error} if error else None
    return a


def _fake_queue(
    *,
    stats_by_engine=None,
    outcomes=None,
    actions_by_status=None,
):
    q = MagicMock()
    q.stats_by_engine.return_value = stats_by_engine or {}
    q.engine_outcome_stats.return_value = outcomes or {
        "positive_count": 0, "negative_count": 0,
        "neutral_count": 0, "total_outcomes": 0,
        "total_revenue": 0.0, "outcome_score": None,
    }

    def _list_by_status(status, *, engine=None, limit=10):
        if actions_by_status is None:
            return []
        return list(actions_by_status.get(status.value, []))[:limit]

    q.list_by_status.side_effect = _list_by_status
    return q


# ─── Zero-activity engine ────────────────────────────────────


class TestNoActivity:

    def test_text_renders_no_activity(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, code = _capture(
                cli._cmd_engine_summary,
                _ns(engine_name="ghost"),
            )
        assert code == 0
        assert "no recorded activity" in out

    def test_json_envelope_has_zero_counts(self, cli):
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out, _ = _capture(
                cli._cmd_engine_summary,
                _ns(engine_name="ghost", json=True),
            )
        data = json.loads(out)
        assert data["engine"] == "ghost"
        assert data["total_activity"] == 0
        assert data["recent"] == []


# ─── Counts + outcomes populated ────────────────────────────


class TestPopulated:

    def test_counts_rendered_in_text(self, cli):
        q = _fake_queue(
            stats_by_engine={
                "loyalty": {
                    "executed": 12, "failed": 2, "rejected": 1,
                    "pending": 0, "approved": 0, "expired": 0,
                },
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "executed" in out
        assert "12" in out
        assert "failed" in out
        assert "TOTAL" in out
        assert "15" in out  # 12 + 2 + 1

    def test_outcomes_score_rendered(self, cli):
        q = _fake_queue(
            stats_by_engine={"loyalty": {"executed": 5}},
            outcomes={
                "positive_count": 7, "negative_count": 3,
                "neutral_count": 1, "total_outcomes": 11,
                "total_revenue": 525.50,
                "outcome_score": 0.7,  # 7 / 10
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "positive=7" in out
        assert "negative=3" in out
        assert "$525.50" in out
        assert "70.0%" in out  # effectiveness score

    def test_n_a_when_no_polarised_outcomes(self, cli):
        q = _fake_queue(
            stats_by_engine={"loyalty": {"executed": 1}},
            outcomes={
                "positive_count": 0, "negative_count": 0,
                "neutral_count": 0, "total_outcomes": 0,
                "total_revenue": 0.0,
                "outcome_score": None,
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "n/a" in out


# ─── Recent activity ────────────────────────────────────────


class TestRecentActivity:

    def test_recent_actions_listed(self, cli):
        q = _fake_queue(
            stats_by_engine={"loyalty": {"executed": 2}},
            actions_by_status={
                "executed": [
                    _fake_action(id_="a1", decided_at=time.time() - 30),
                    _fake_action(id_="a2", decided_at=time.time() - 120),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "mint_loyalty_code" in out
        assert "30s ago" in out or "0m ago" in out

    def test_recent_n_caps_listing(self, cli):
        actions = [
            _fake_action(
                id_=f"a{i}", decided_at=time.time() - i * 10,
            ) for i in range(10)
        ]
        q = _fake_queue(
            stats_by_engine={"loyalty": {"executed": 10}},
            actions_by_status={"executed": actions},
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_engine_summary, _ns(recent_n=3, json=True),
            )
        data = json.loads(out)
        assert len(data["recent"]) == 3

    def test_failed_action_surfaces_error(self, cli):
        q = _fake_queue(
            stats_by_engine={"loyalty": {"failed": 1}},
            actions_by_status={
                "failed": [
                    _fake_action(
                        id_="bad", status_value="failed",
                        error="adapter_failed: scope_missing",
                    ),
                ],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "scope_missing" in out


# ─── --json envelope ────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        q = _fake_queue(
            stats_by_engine={
                "loyalty": {"executed": 5, "failed": 1},
            },
            outcomes={
                "positive_count": 3, "negative_count": 1,
                "neutral_count": 0, "total_outcomes": 4,
                "total_revenue": 100.0, "outcome_score": 0.75,
            },
            actions_by_status={
                "executed": [_fake_action(id_="e1")],
                "failed": [_fake_action(id_="f1", status_value="failed")],
            },
        )
        with patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_engine_summary, _ns(json=True),
            )
        data = json.loads(out)
        assert data["engine"] == "loyalty"
        assert data["counts_by_status"]["executed"] == 5
        assert data["counts_by_status"]["failed"] == 1
        assert data["total_activity"] == 6
        assert data["outcomes"]["outcome_score"] == 0.75
        # Recent merges EXECUTED + FAILED, ordered newest first
        assert len(data["recent"]) == 2


# ─── Quarantine section ──────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def _alert_history_no_guard():
    """Lift Pattern J guard so the engine summary can read
    seeded alert_history data inside tests."""
    with patch(
        "core.approval.alert_history._is_test_environment",
        return_value=False,
    ):
        yield


class TestQuarantineSection:
    """``engine summary`` surfaces quarantine state + alert
    streak so operators can diagnose 'why is X paused?' from
    one command."""

    def test_clean_engine_no_section_in_text(
        self, cli, data_dir, _alert_history_no_guard,
    ):
        """Healthy engine + no alerts -> section omitted in text."""
        q = _fake_queue(stats_by_engine={"loyalty": {"executed": 5}})
        with patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "Quarantine:" not in out

    def test_alert_paused_renders_text(
        self, cli, data_dir, _alert_history_no_guard,
    ):
        from core.approval import quarantine
        quarantine.add_alert_pause("loyalty")
        q = _fake_queue(stats_by_engine={"loyalty": {"executed": 5}})
        with patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "Quarantine:" in out
        assert "alert_paused" in out

    def test_alert_streak_renders_text(
        self, cli, data_dir, _alert_history_no_guard,
    ):
        from core.approval import alert_history
        day = 86400.0
        now = time.time()
        # 3 distinct days of firings
        for i in range(3):
            alert_history.record_alerts(
                [
                    type("FA", (), {
                        "engine": "loyalty",
                        "drop": 0.3,
                        "recent_score": 0.4,
                        "baseline_score": 0.7,
                    })()
                ],
                now=now - day * (2 - i) - 100,
            )
        q = _fake_queue(stats_by_engine={"loyalty": {"executed": 5}})
        with patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out, _ = _capture(cli._cmd_engine_summary, _ns())
        assert "Quarantine:" in out
        assert "Alert streak (last 7d): 3 day(s)" in out
        assert "Last alert firing:" in out

    def test_json_envelope_includes_quarantine(
        self, cli, data_dir, _alert_history_no_guard,
    ):
        from core.approval import quarantine
        quarantine.exempt_engine("loyalty")
        q = _fake_queue(stats_by_engine={"loyalty": {"executed": 5}})
        with patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out, _ = _capture(
                cli._cmd_engine_summary, _ns(json=True),
            )
        data = json.loads(out)
        assert "quarantine" in data
        assert data["quarantine"]["exempt"] is True
        assert data["quarantine"]["released"] is False
        assert data["quarantine"]["alert_paused"] is False
        assert data["quarantine"]["alert_streak_7d"] == 0
        assert data["quarantine"]["last_alert_at"] is None

    def test_quarantine_probe_failure_doesnt_break(
        self, cli, data_dir, _alert_history_no_guard,
    ):
        """If load_state raises, the section is just empty -- the
        summary still renders."""
        q = _fake_queue(stats_by_engine={"loyalty": {"executed": 5}})
        with patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ), patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("disk gone"),
        ):
            out, code = _capture(cli._cmd_engine_summary, _ns())
        # Summary still renders despite quarantine probe failure
        assert code == 0
        assert "loyalty" in out
