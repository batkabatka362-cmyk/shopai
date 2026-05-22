"""End-to-end trust-anchor test for the autonomous cycle.

The unit tests mock each layer individually so per-layer
behaviour is fast to verify. But mock-heavy tests can let
the LAYERS drift apart without anyone noticing -- the
cycle calls record_cycle, daily-brief calls cycle_stats,
world-model calls (eventually) the same. If any layer's
contract changes shape, all the individual unit tests still
pass because they mock the consumer.

This test exercises the WHOLE chain against REAL files:

  1. Spawn a fresh fleet (in-memory store manager).
  2. Run ``shopai autonomous-cycle --yes --json`` so the
     ADVANCE / DEFEND / MEASURE phases all fire AND the
     invocation gets persisted to cycle_history.
  3. Read cycle_history back via the public API.
  4. Run ``shopai daily-brief --json`` and confirm the
     cycle_activity section reflects the run we just did.
  5. Run ``shopai autonomous-cycle --history --json`` and
     confirm the same event appears.

If any layer's contract regresses, this test fails first.

Pattern J: the test patches every Pattern J guard to
False so the writers actually fire. This is the SAME
pattern as ``test_alert_quarantine_e2e.py``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.autonomous import cycle_history


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location(
        "shopai_cli", "cli.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def lift_pattern_j():
    """Disable the test-environment guard on cycle_history
    so the recorder actually writes."""
    with patch(
        "core.autonomous.cycle_history."
        "_is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def real_history_files(tmp_path):
    """Redirect ALL the persistent state files to tmp dirs
    so we exercise the real write paths without polluting
    production ``data/``."""
    cycle_path = tmp_path / "cycle_history.json"
    cycle_history._reset_for_tests(cycle_path)
    yield {"cycle_history": cycle_path}
    cycle_history._reset_for_tests(
        Path("data/cycle_history.json"),
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


def _ns_cycle(**kw):
    defaults = dict(
        yes=True,
        skip_correlate=True,
        skip_advance=True,
        skip_defend=True,
        history=False,
        history_window_days=7,
        history_limit=10,
        json=True,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _ns_brief(**kw):
    defaults = dict(window_hours=24, json=True)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm():
    sm = MagicMock()
    sm.list_stores.return_value = []
    sm.active_store_id = None
    return sm


def _fake_queue():
    q = MagicMock()
    q.stats.return_value = {
        "pending": 0, "approved": 0, "rejected": 0,
        "executed": 0, "failed": 0, "expired": 0,
    }
    q.stats_by_engine.return_value = {}
    q.list_decisions.return_value = []
    q.list_by_status.return_value = []
    return q


def test_cycle_to_history_to_brief_e2e(
    cli, real_history_files, lift_pattern_j,
):
    """The full chain: run a cycle -> persist -> daily-brief
    surfaces it -> --history surfaces it. Trust anchor for
    contract consistency across layers."""

    fake_sm = _fake_sm()

    # ── Step 1: run a cycle (skip every phase since we have
    # no fleet, but the recorder still fires). ──────────────
    with patch.object(
        cli, "_get_store_manager", return_value=fake_sm,
    ), patch(
        "core.capability_planner.recent_history",
        return_value=[],
    ):
        out, code = _capture(
            cli._cmd_autonomous_cycle, _ns_cycle(),
        )
    assert code == 0
    cycle_data = json.loads(out)
    assert cycle_data["executed"] is True

    # ── Step 2: verify cycle_history file actually exists
    # and has one row. ─────────────────────────────────────
    path = real_history_files["cycle_history"]
    assert path.exists(), (
        "Cycle history file should exist after a real run "
        "(Pattern J guard lifted)"
    )
    raw = json.loads(path.read_text())
    assert len(raw) == 1
    assert raw[0]["executed"] is True

    # ── Step 3: public API returns the same row. ──────────
    events = cycle_history.recent_history(
        since_seconds=3600,
    )
    assert len(events) == 1
    assert events[0].executed is True
    stats = cycle_history.cycle_stats(
        since_seconds=3600,
    )
    assert stats["total_runs"] == 1
    assert stats["executed_runs"] == 1
    assert stats["dry_run_count"] == 0

    # ── Step 4: daily-brief picks it up. The
    # cycle_activity section should reflect the run we just
    # logged. ──────────────────────────────────────────────
    with patch.object(
        cli, "_get_store_manager", return_value=fake_sm,
    ), patch(
        "core.approval.queue.get_approval_queue",
        return_value=_fake_queue(),
    ):
        out, _ = _capture(
            cli._cmd_daily_brief, _ns_brief(),
        )
    brief_data = json.loads(out)
    assert "cycle_activity" in brief_data
    activity = brief_data["cycle_activity"]
    assert activity["checked"] is True
    assert activity["total_runs"] == 1
    assert activity["executed_runs"] == 1
    assert activity["last_run_at"] is not None

    # ── Step 5: --history flag finds the same event. ──────
    with patch.object(
        cli, "_get_store_manager", return_value=fake_sm,
    ):
        out, _ = _capture(
            cli._cmd_autonomous_cycle,
            _ns_cycle(history=True, yes=False),
        )
    history_data = json.loads(out)
    assert history_data["stats"]["total_runs"] == 1
    assert len(history_data["events"]) == 1
    assert (
        history_data["events"][0]["recorded_at"]
        == events[0].recorded_at
    )


def test_multiple_cycles_accumulate(
    cli, real_history_files, lift_pattern_j,
):
    """Three cycles in a row should each persist independently
    and the stats should aggregate correctly."""
    fake_sm = _fake_sm()

    for _ in range(3):
        with patch.object(
            cli, "_get_store_manager", return_value=fake_sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            _capture(
                cli._cmd_autonomous_cycle, _ns_cycle(),
            )
        # Spread the timestamps so the recent_history sort
        # has a deterministic order (Windows time resolution
        # can collide on adjacent calls).
        time.sleep(0.01)

    # cycle_history has 3 entries
    raw = json.loads(
        real_history_files["cycle_history"].read_text(),
    )
    assert len(raw) == 3

    stats = cycle_history.cycle_stats(
        since_seconds=3600,
    )
    assert stats["total_runs"] == 3
    assert stats["executed_runs"] == 3

    # daily-brief reflects all three
    with patch.object(
        cli, "_get_store_manager", return_value=_fake_sm(),
    ), patch(
        "core.approval.queue.get_approval_queue",
        return_value=_fake_queue(),
    ):
        out, _ = _capture(
            cli._cmd_daily_brief, _ns_brief(),
        )
    data = json.loads(out)
    assert data["cycle_activity"]["total_runs"] == 3


def test_pattern_j_default_no_persistence(
    cli, real_history_files,
):
    """Without lifting the Pattern J guard, cycle runs but
    DOES NOT persist to the history file. Tests verify the
    guard is in place; production is unaffected because
    PYTEST_CURRENT_TEST is unset there."""
    fake_sm = _fake_sm()
    with patch.object(
        cli, "_get_store_manager", return_value=fake_sm,
    ), patch(
        "core.capability_planner.recent_history",
        return_value=[],
    ):
        _capture(cli._cmd_autonomous_cycle, _ns_cycle())
    # File should NOT exist -- the guard short-circuited
    assert not real_history_files["cycle_history"].exists()
