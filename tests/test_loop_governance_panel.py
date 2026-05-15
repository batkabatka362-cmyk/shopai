"""Tests for the governance panel added to ``shopai loop`` (PR #163).

The panel surfaces the self-regulating loop's live state:
  - auto-approve allowlist (PR #161)
  - quarantine exemptions + releases (PR #162)
  - last-24h counters for auto-approved + auto-quarantined
    decisions (sourced from decision_log)

Coverage:
  - probe is best-effort (missing module / corrupt config →
    empty defaults, not a crash)
  - 24h counter window is correctly bounded
  - text render includes the governance panel
  - allowlist + exemptions surface in render
"""
from __future__ import annotations

import argparse
import importlib.util
import time
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
    """Redirect both governance config files + the approval
    queue to a temp dir."""
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"data_dir": tmp_path, "queue": fresh}
    fresh._conn.close()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── _build_loop_dict["governance"] ────────────────────────────


class TestGovernanceProbe:

    def test_empty_state_renders_empty_lists_and_zero_counters(
        self, cli, isolated_state,
    ):
        payload = cli._build_loop_dict()
        gov = payload["governance"]
        assert gov["auto_approve_allowlist"] == []
        assert gov["quarantine_exemptions"] == []
        assert gov["quarantine_released"] == []
        assert gov["recent_auto_approved"] == 0
        assert gov["recent_auto_quarantined"] == 0

    def test_allowlist_surfaces(self, cli, isolated_state):
        from core.approval.auto_approve import enable_engine
        enable_engine("cart_recovery")
        enable_engine("loyalty")
        payload = cli._build_loop_dict()
        assert set(payload["governance"]["auto_approve_allowlist"]) == {
            "cart_recovery", "loyalty",
        }

    def test_quarantine_exemptions_surface(self, cli, isolated_state):
        from core.approval.quarantine import (
            exempt_engine, release_engine,
        )
        exempt_engine("returns_management")
        release_engine("inventory")
        payload = cli._build_loop_dict()
        gov = payload["governance"]
        assert gov["quarantine_exemptions"] == ["returns_management"]
        assert gov["quarantine_released"] == ["inventory"]


class TestAutoDecisionCounters:

    def test_counts_recent_auto_approved(self, cli, isolated_state):
        """Counter increments for decision_log rows with
        decided_by='auto_threshold' within the 24h window."""
        q = isolated_state["queue"]
        # Seed an action then manually approve via the
        # 'auto_threshold' actor — the queue write path doesn't
        # care who the actor is, decision_log just records it.
        for i in range(3):
            a = q.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="", confidence=0.95,
            )
            q.approve(a.id, decided_by="auto_threshold")
        payload = cli._build_loop_dict()
        assert payload["governance"]["recent_auto_approved"] == 3
        assert payload["governance"]["recent_auto_quarantined"] == 0

    def test_counts_recent_auto_quarantined(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        for i in range(2):
            a = q.enqueue(
                engine="x", action_type="y", capability="z",
                params={}, narrative="",
            )
            q.reject(a.id, decided_by="auto_quarantine")
        payload = cli._build_loop_dict()
        assert payload["governance"]["recent_auto_quarantined"] == 2
        assert payload["governance"]["recent_auto_approved"] == 0

    def test_old_decisions_excluded(self, cli, isolated_state):
        """Decisions older than 24h don't count toward the
        recent counters."""
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="auto_threshold")
        # Backdate the decision row to 36h ago
        q._conn.execute(
            "UPDATE decision_log SET occurred_at = ? "
            "WHERE action_id = ?",
            (time.time() - 36 * 3600, a.id),
        )
        q._conn.commit()
        payload = cli._build_loop_dict()
        assert payload["governance"]["recent_auto_approved"] == 0

    def test_manual_decisions_not_counted(self, cli, isolated_state):
        """Only decided_by='auto_threshold' or 'auto_quarantine'
        contribute to the counters — manual operator approvals
        and rejections don't."""
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="alice")
        b = q.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.reject(b.id, decided_by="alice")
        payload = cli._build_loop_dict()
        gov = payload["governance"]
        assert gov["recent_auto_approved"] == 0
        assert gov["recent_auto_quarantined"] == 0


# ─── Resilience ────────────────────────────────────────────────


class TestResilience:

    def test_auto_approve_module_failure_renders_empty(
        self, cli, isolated_state,
    ):
        """If load_config raises, the panel falls back to its
        empty default rather than failing the whole render."""
        with patch(
            "core.approval.auto_approve.load_config",
            side_effect=RuntimeError("config broken"),
        ):
            payload = cli._build_loop_dict()
        assert payload["governance"]["auto_approve_allowlist"] == []

    def test_quarantine_module_failure_renders_empty(
        self, cli, isolated_state,
    ):
        with patch(
            "core.approval.quarantine.load_state",
            side_effect=RuntimeError("state broken"),
        ):
            payload = cli._build_loop_dict()
        assert payload["governance"]["quarantine_exemptions"] == []
        assert payload["governance"]["quarantine_released"] == []

    def test_decision_log_failure_keeps_zero_counters(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        with patch.object(
            q, "list_decisions",
            side_effect=RuntimeError("db lock"),
        ):
            payload = cli._build_loop_dict()
        assert payload["governance"]["recent_auto_approved"] == 0
        assert payload["governance"]["recent_auto_quarantined"] == 0


# ─── Text render ───────────────────────────────────────────────


class TestTextRender:

    def test_governance_panel_in_render(self, cli, isolated_state):
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=False, top=3, watch=0),
        )
        assert "Governance:" in out
        assert "Auto-approve allowlist" in out
        assert "Quarantine exemptions" in out
        assert "Last 24h" in out

    def test_render_shows_enabled_engines(self, cli, isolated_state):
        from core.approval.auto_approve import enable_engine
        from core.approval.quarantine import exempt_engine
        enable_engine("cart_recovery")
        exempt_engine("returns_management")
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=False, top=3, watch=0),
        )
        assert "cart_recovery" in out
        assert "returns_management" in out

    def test_render_omits_released_line_when_empty(
        self, cli, isolated_state,
    ):
        """The released line is conditional — empty releases
        don't take screen space (it's the operator-override case,
        not the steady state)."""
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=False, top=3, watch=0),
        )
        assert "Quarantine released" not in out

    def test_render_shows_released_line_when_set(
        self, cli, isolated_state,
    ):
        from core.approval.quarantine import release_engine
        release_engine("inventory")
        out = _capture(
            cli._cmd_loop,
            argparse.Namespace(json=False, top=3, watch=0),
        )
        assert "Quarantine released" in out
        assert "inventory" in out
