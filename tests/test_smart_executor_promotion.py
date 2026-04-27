"""Tests for SmartExecutor ↔ PromotionTracker integration.

Coverage:
  1. First-time action with no memory → SIMULATE regardless of
     tracker state (Rule 2 in `_base_mode_from_risk`).
  2. With memory + low-risk + tracker at SIMULATE → caps at
     SIMULATE (tracker hasn't earned promotion yet).
  3. With memory + low-risk + tracker at LIVE → mode goes LIVE.
  4. High-risk action_type — tracker can't push past DRY_RUN
     ceiling (Rule 3).
  5. Successful DRY_RUN execution increments the tracker.
  6. Successful SIMULATE execution does NOT increment (synthetic).
  7. Failure (score ≤ 2.0) demotes the tracker.
  8. Per-(engine, action) keying — tracker entries don't bleed.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_tracker(tmp_path: Path, monkeypatch):
    from execution import promotion_tracker as pt

    fresh = pt.PromotionTracker(
        db_path=tmp_path / "promo.db", promote_threshold=3,
    )
    monkeypatch.setattr(pt, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def executor(isolated_tracker):
    from execution.smart_executor import SmartExecutor

    se = SmartExecutor()
    # Skip MemoryIntelligence / DataArchitecture / LearningLoop
    # init — only the promotion tracker matters for these tests.
    se._memory_intel = None
    se._data_arch = None
    se._learning_loop = None
    se._ab_testing = None
    se._promotion_tracker = isolated_tracker
    return se


# ─── _determine_mode integration ─────────────────────────────────


class TestDetermineMode:

    def test_no_memory_forces_simulate_regardless_of_tracker(
        self, executor, isolated_tracker,
    ):
        # Tracker pre-loaded to LIVE — but Rule 2 (no memory) wins.
        for _ in range(6):
            isolated_tracker.record_success("update_price")
        assert isolated_tracker.current_tier("update_price") == "live"

        mode = executor._determine_mode(
            "update_price", confidence=0.9,
            memory={"total_memories": 0},
        )
        assert mode == "simulate"

    def test_low_risk_with_memory_simulate_when_tracker_simulate(
        self, executor,
    ):
        # alert is low-risk, no failures, meets confidence floor.
        # Base ceiling lifts to "live" (Rule 6) but tracker hasn't
        # earned the promotion → final mode stays "simulate".
        memory = {"total_memories": 5, "best_events": [], "failures": []}
        mode = executor._determine_mode(
            "alert", confidence=0.9, memory=memory,
        )
        assert mode == "simulate"

    def test_low_risk_with_promoted_tracker_goes_live(
        self, executor, isolated_tracker,
    ):
        for _ in range(6):
            isolated_tracker.record_success("alert")
        assert isolated_tracker.current_tier("alert") == "live"

        memory = {"total_memories": 5, "best_events": [], "failures": []}
        mode = executor._determine_mode(
            "alert", confidence=0.9, memory=memory,
        )
        assert mode == "live"

    def test_high_risk_caps_at_dry_run_even_when_tracker_live(
        self, executor, isolated_tracker,
    ):
        for _ in range(6):
            isolated_tracker.record_success("update_inventory")
        assert isolated_tracker.current_tier("update_inventory") == "live"

        # Memory has 3+ best_events, confidence above floor → base
        # ceiling = dry_run for high-risk. Tracker says live; min
        # of (dry_run, live) = dry_run.
        memory = {
            "total_memories": 10,
            "best_events": [{"action": "update_inventory"}] * 3,
            "failures": [],
        }
        mode = executor._determine_mode(
            "update_inventory", confidence=0.95, memory=memory,
        )
        assert mode == "dry_run"

    def test_recent_failure_in_memory_forces_simulate(
        self, executor, isolated_tracker,
    ):
        # Tracker says LIVE — but memory says this action recently
        # failed, so base = simulate (Rule 4).
        for _ in range(6):
            isolated_tracker.record_success("update_price")
        memory = {
            "total_memories": 5,
            "best_events": [],
            "failures": [{"action": "update_price"}],
        }
        mode = executor._determine_mode(
            "update_price", confidence=0.95, memory=memory,
        )
        assert mode == "simulate"


# ─── outcome recording ─────────────────────────────────────────


class TestOutcomeRecording:

    def test_dry_run_success_promotes_tracker(
        self, executor, isolated_tracker,
    ):
        action = {"type": "alert", "confidence": 0.9, "params": {}}
        for _ in range(3):
            executor._record_execution(
                action,
                predicted={"success": True, "type": "alert_simulation"},
                actual={"success": True, "type": "alert_simulation"},
                score=4.5,
                mode="dry_run",
            )
        # 3 successes at SIMULATE → DRY_RUN; tracker counter resets.
        assert isolated_tracker.current_tier("alert") == "dry_run"

    def test_simulate_success_does_not_promote(
        self, executor, isolated_tracker,
    ):
        # Pure simulations are synthetic; they don't earn trust.
        action = {"type": "alert", "confidence": 0.9, "params": {}}
        for _ in range(5):
            executor._record_execution(
                action,
                predicted={"success": True},
                actual={"success": True},
                score=4.5,
                mode="simulate",
            )
        assert isolated_tracker.current_tier("alert") == "simulate"

    def test_low_score_failure_demotes_tracker(
        self, executor, isolated_tracker,
    ):
        for _ in range(6):
            isolated_tracker.record_success("alert")
        assert isolated_tracker.current_tier("alert") == "live"

        action = {"type": "alert", "confidence": 0.9, "params": {}}
        executor._record_execution(
            action,
            predicted={"success": False},
            actual={"success": False, "error": "scope_missing"},
            score=1.5,
            mode="live",
        )
        # Score ≤ 2.0 demotes regardless of mode.
        assert isolated_tracker.current_tier("alert") == "simulate"

    def test_live_success_increments_promoted_tracker(
        self, executor, isolated_tracker,
    ):
        # Already at LIVE; further successes shouldn't push past
        # the top of the ladder, but they shouldn't demote either.
        for _ in range(6):
            isolated_tracker.record_success("alert")
        action = {"type": "alert", "confidence": 0.9, "params": {}}
        for _ in range(3):
            executor._record_execution(
                action,
                predicted={"success": True},
                actual={"success": True},
                score=4.5,
                mode="live",
            )
        assert isolated_tracker.current_tier("alert") == "live"


# ─── per-action_type independence ──────────────────────────────


class TestPerActionIndependence:

    def test_promotion_for_one_action_does_not_affect_another(
        self, isolated_tracker,
    ):
        for _ in range(6):
            isolated_tracker.record_success("alert")
        # update_price still untouched.
        assert isolated_tracker.current_tier("alert") == "live"
        assert isolated_tracker.current_tier("update_price") == "simulate"
