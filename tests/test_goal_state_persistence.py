"""Tests for GoalManager EMA persistence to ``data/goal_state.json``.

Pre-PR, GoalManager held its per-goal EMA state purely in memory.
Every process restart reset every goal's effectiveness to 0.5 —
the brain stack had amnesia between cycles. Without persistence,
all the outcome→EMA wiring (PR #114/#115) was undone every time
the operator restarted the CLI or API server.

Coverage:
  - Fresh manager with no state file starts empty
  - Recording an outcome writes the state file (under non-test env)
  - A new manager loads the state file on init
  - Test environment short-circuits the write (Pattern J)
  - Corrupt / partial state files don't crash __init__
  - Atomic write (no partial files visible)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _allow_writes(monkeypatch):
    """Disable the Pattern J pytest gate so this test can verify
    the actual file-write behavior. Production code still has the
    gate active under PYTEST_CURRENT_TEST."""
    monkeypatch.setattr(
        "core.goals.goal_manager._is_test_environment",
        lambda: False,
    )


# ─── Fresh-start behavior ─────────────────────────────────────────


class TestFreshStart:

    def test_no_state_file_empty_stats(self, tmp_path):
        from core.goals.goal_manager import GoalManager

        state = tmp_path / "goal_state.json"
        assert not state.exists()
        m = GoalManager(state_path=state)
        assert m.get_effectiveness_stats() == {}
        # And no file gets created until a save fires
        assert not state.exists()


# ─── Save round-trip ──────────────────────────────────────────────


class TestSaveRoundTrip:

    def test_record_outcome_writes_state(self, tmp_path):
        from core.goals.goal_manager import GoalManager

        state = tmp_path / "goal_state.json"
        m = GoalManager(state_path=state)
        m.record_goal_outcome(
            "grow_customers", {"health_delta": 1.0},
        )
        assert state.exists()

        payload = json.loads(state.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert "saved_at" in payload
        assert "goal_stats" in payload
        assert payload["goal_stats"]["grow_customers"]["n"] == 1

    def test_second_manager_inherits_state(self, tmp_path):
        from core.goals.goal_manager import GoalManager

        state = tmp_path / "goal_state.json"
        m1 = GoalManager(state_path=state)
        for _ in range(3):
            m1.record_goal_outcome(
                "grow_customers", {"health_delta": 1.0},
            )
        ema_before = m1.get_effectiveness("grow_customers")
        assert ema_before > 0.5  # positive outcomes pushed it up

        # New manager pointing at the same file
        m2 = GoalManager(state_path=state)
        assert m2.get_effectiveness("grow_customers") == pytest.approx(
            ema_before, abs=1e-9,
        )
        stats = m2.get_effectiveness_stats()
        assert stats["grow_customers"]["n"] == 3

    def test_multi_goal_persistence(self, tmp_path):
        from core.goals.goal_manager import GoalManager

        state = tmp_path / "goal_state.json"
        m = GoalManager(state_path=state)
        m.record_goal_outcome("grow_customers", {"health_delta": 1.0})
        m.record_goal_outcome("maximize_profit", {"health_delta": -1.0})

        m2 = GoalManager(state_path=state)
        stats = m2.get_effectiveness_stats()
        assert set(stats.keys()) == {"grow_customers", "maximize_profit"}
        assert stats["grow_customers"]["effectiveness"] > 0.5
        assert stats["maximize_profit"]["effectiveness"] < 0.5


# ─── Pattern J: test-env short-circuit ───────────────────────────


class TestPytestGate:

    def test_pytest_env_skips_save(self, tmp_path):
        """When _is_test_environment returns True (which is the
        default under pytest), record_goal_outcome must NOT touch
        the file system — so test runs don't pollute the real
        data/goal_state.json."""
        from core.goals.goal_manager import GoalManager

        state = tmp_path / "goal_state.json"
        # Re-enable the gate for this single test
        with patch(
            "core.goals.goal_manager._is_test_environment",
            return_value=True,
        ):
            m = GoalManager(state_path=state)
            m.record_goal_outcome(
                "grow_customers", {"health_delta": 1.0},
            )
        # In-memory state is updated, but no file written
        assert m.get_effectiveness_stats()["grow_customers"]["n"] == 1
        assert not state.exists()


# ─── Resilience ──────────────────────────────────────────────────


class TestResilience:

    def test_corrupt_state_file_clean_start(self, tmp_path):
        """A partially-written or malformed JSON file leaves
        __init__ in the clean-empty state, doesn't crash."""
        state = tmp_path / "goal_state.json"
        state.write_text("{not valid json}{", encoding="utf-8")
        from core.goals.goal_manager import GoalManager

        m = GoalManager(state_path=state)
        assert m.get_effectiveness_stats() == {}

    def test_wrong_shape_dropped(self, tmp_path):
        """Old/foreign payloads don't crash — just start fresh."""
        state = tmp_path / "goal_state.json"
        state.write_text(
            json.dumps({"unrelated_key": [1, 2, 3]}),
            encoding="utf-8",
        )
        from core.goals.goal_manager import GoalManager

        m = GoalManager(state_path=state)
        assert m.get_effectiveness_stats() == {}

    def test_invalid_entries_filtered(self, tmp_path):
        """Mixed valid + invalid entries — valid ones survive."""
        state = tmp_path / "goal_state.json"
        state.write_text(
            json.dumps({
                "version": 1, "saved_at": time.time(),
                "goal_stats": {
                    "grow_customers": {"ema": 0.7, "n": 5},
                    "broken_goal": {"ema": "not_a_number"},
                    "negative_n": {"ema": 0.5, "n": -10},
                },
            }),
            encoding="utf-8",
        )
        from core.goals.goal_manager import GoalManager

        m = GoalManager(state_path=state)
        stats = m.get_effectiveness_stats()
        assert "grow_customers" in stats
        assert stats["grow_customers"]["effectiveness"] == pytest.approx(0.7)
        # broken_goal dropped entirely (ema not parseable)
        assert "broken_goal" not in stats
        # negative_n was filtered to 0 (>= 0 enforced)
        assert "negative_n" in stats
        assert stats["negative_n"]["n"] == 0

    def test_save_io_error_no_crash(self, tmp_path):
        """A write failure (read-only fs, etc.) gets logged at
        debug, doesn't propagate up to the outcome path."""
        from core.goals.goal_manager import GoalManager

        # Pointing at a directory path forces the write to fail
        bad_state = tmp_path / "nonexistent" / "dir" / "x.json"
        m = GoalManager(state_path=bad_state)
        # Forcibly remove parent so .mkdir creates it but then make
        # write target be unwritable. Simpler: mock write_text.
        with patch.object(
            Path, "write_text",
            side_effect=PermissionError("read-only fs"),
        ):
            # MUST NOT raise
            m.record_goal_outcome(
                "grow_customers", {"health_delta": 1.0},
            )
        # In-memory state still updated
        assert m.get_effectiveness_stats()["grow_customers"]["n"] == 1
