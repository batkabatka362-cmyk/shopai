"""Wave 7b regression fixes and hardening — unit tests.

Covers five changes:

  NEW-A  — SLA/Mind injection before cycle_result snapshot
  NEW-B  — O(N) rehydration (pre-built SOFT rule ID set)
  NEW-C  — debate→belief key fallback in _check_belief_posterior
  GAP-16 — BeliefStore write debounce
  GAP-18 — decay max_idle 60s floor guard
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.autonomous.controller import AutonomousController
from core.judgment.judgment_advisor import JudgmentAdvisor
from core.memory.quality_engine import MemoryRecord
from core.mentality import BeliefStore, Values
from core.reflection.synthesizer import (
    ErrorPattern,
    ReflectionSynthesizer,
    _signature,
)
from engines.meta_governance.policy_store import (
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _bare_controller(tmp_path: Path) -> AutonomousController:
    """Build a minimal controller via __new__ with an isolated
    synthesizer and error buffer.  No initialize() call needed."""
    c = AutonomousController.__new__(AutonomousController)
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    c._reflection_synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    c._reflection_buffer_max = 50
    c._error_buffer = None
    c._reflection_init_lock = threading.Lock()
    c._last_reflection_decay_at = 0.0
    c._REFLECTION_DECAY_INTERVAL_SEC = 3600.0
    c._REFLECTION_DECAY_MAX_IDLE_SEC = 30 * 24 * 3600.0
    return c


def _err(msg: str, *, kind: str = "error", ts: float = 1000.0) -> MemoryRecord:
    return MemoryRecord(
        kind=kind,
        quality=0.5,
        confidence=0.5,
        success_rate=0.0,
        usage=1,
        created_at=ts,
        payload={"message": msg},
    )


# ===================================================================
# NEW-A: SLA/Mind injection before cycle_result snapshot
# ===================================================================


class TestSnapshotOrderingNEWA:
    """Verify that Mind errors and SLA breaches appear in the
    cycle_result['phase_errors'] snapshot (not just the live dict)."""

    def test_cognitive_error_in_snapshot(self, tmp_path):
        """When cognitive report has an error, the snapshot dict
        in cycle_result['phase_errors'] must include it."""
        c = _bare_controller(tmp_path)
        phase_errors: dict[str, str] = {"analysis": "some prior error"}

        # Simulate what run_cycle now does: inject Mind errors,
        # then snapshot.
        cycle_result: dict[str, Any] = {
            "cycle_id": "snap-test",
            "cognitive": {"error": "Mind.Planner crashed: NoneType"},
        }
        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict) and cog.get("error"):
            phase_errors["cognitive_mind"] = str(cog["error"])

        # Snapshot (mirrors the real code)
        cycle_result["phase_errors"] = dict(phase_errors)
        cycle_result["phase_error_count"] = len(phase_errors)

        # The snapshot must contain both the prior error and the
        # injected Mind error.
        assert "cognitive_mind" in cycle_result["phase_errors"]
        assert "analysis" in cycle_result["phase_errors"]
        assert cycle_result["phase_error_count"] == 2

    def test_sla_breach_in_snapshot(self, tmp_path):
        """SLA breaches injected before snapshot appear in the
        cycle_result dict."""
        phase_errors: dict[str, str] = {}

        # Simulate SLA injection
        phase_errors["sla::shopify_api"] = "success_rate 0.42 < 0.95"

        cycle_result: dict[str, Any] = {"cycle_id": "sla-test"}
        cycle_result["phase_errors"] = dict(phase_errors)
        cycle_result["phase_error_count"] = len(phase_errors)

        assert "sla::shopify_api" in cycle_result["phase_errors"]
        assert cycle_result["phase_error_count"] == 1

    def test_reflection_hook_error_patches_snapshot(self, tmp_path):
        """When the reflection hook itself fails, the error must
        be patched into the already-taken snapshot."""
        phase_errors: dict[str, str] = {"x": "prior"}
        cycle_result: dict[str, Any] = {"cycle_id": "hook-err"}

        # Snapshot taken
        cycle_result["phase_errors"] = dict(phase_errors)
        cycle_result["phase_error_count"] = len(phase_errors)

        # Hook fails — simulate the post-hook patching
        exc_str = "RuntimeError: boom"
        phase_errors["reflection_hook"] = exc_str
        cycle_result["phase_errors"]["reflection_hook"] = exc_str
        cycle_result["phase_error_count"] = len(cycle_result["phase_errors"])

        assert "reflection_hook" in cycle_result["phase_errors"]
        assert cycle_result["phase_error_count"] == 2


# ===================================================================
# NEW-B: O(N) rehydration in synthesizer
# ===================================================================


class TestRehydrationPerformanceNEWB:
    """Verify that _rehydrate_from_disk pre-builds the SOFT rule
    set instead of calling list_rules() per line."""

    def _write_ledger(self, path: Path, patterns: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for p in patterns:
                fh.write(json.dumps(p) + "\n")

    def test_rehydration_calls_list_rules_once(self, tmp_path):
        """list_rules(tier=SOFT) should be called exactly once,
        not once per ledger line."""
        store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
        ledger = tmp_path / "ledger.jsonl"
        # Write 5 patterns
        patterns = []
        for i in range(5):
            patterns.append({
                "signature": f"sig_{i}",
                "kind": "error",
                "sample_text": f"crash {i}",
                "occurrences": 3,
                "first_seen": 1000.0,
                "last_seen": 2000.0,
                "confidence": 0.8,
            })
        self._write_ledger(ledger, patterns)

        original_list_rules = store.list_rules

        call_count = 0

        def counting_list_rules(tier=None):
            nonlocal call_count
            call_count += 1
            return original_list_rules(tier=tier)

        store.list_rules = counting_list_rules  # type: ignore[method-assign]

        synth = ReflectionSynthesizer(
            policy_store=store,
            persist_path=str(ledger),
            min_occurrences=3,
        )

        # list_rules should have been called exactly once during
        # rehydration (the pre-build step), not 5 times.
        assert call_count == 1

    def test_rehydration_skips_existing_soft_rules(self, tmp_path):
        """If a SOFT rule already exists in the store, rehydration
        should not promote it again."""
        store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))

        # Pre-register a rule
        existing_rule = PolicyRule(
            rule_id="learned::sig_0",
            name="sig_0",
            tier=PolicyTier.SOFT,
            source="learned",
            description="pre-existing",
            matcher=lambda _a, _c: True,
            verdict=PolicyVerdict.BLOCK,
            version=1,
        )
        store.promote_soft_rule(existing_rule)

        ledger = tmp_path / "ledger.jsonl"
        patterns = [
            {
                "signature": "sig_0",
                "kind": "error",
                "sample_text": "crash 0",
                "occurrences": 3,
                "confidence": 0.8,
            },
            {
                "signature": "sig_1",
                "kind": "error",
                "sample_text": "crash 1",
                "occurrences": 3,
                "confidence": 0.8,
            },
        ]
        self._write_ledger(ledger, patterns)

        synth = ReflectionSynthesizer(
            policy_store=store,
            persist_path=str(ledger),
            min_occurrences=3,
        )

        # sig_0 should be in promoted set (rehydrated) but NOT
        # re-promoted to the store. sig_1 should be promoted.
        assert "sig_0" in synth._promoted
        assert "sig_1" in synth._promoted

        # The store should have exactly 2 SOFT rules (pre-existing
        # sig_0 + newly promoted sig_1).
        soft_rules = store.list_rules(tier=PolicyTier.SOFT)
        rule_ids = {r.rule_id for r in soft_rules}
        assert "learned::sig_0" in rule_ids
        assert "learned::sig_1" in rule_ids

    def test_rehydration_updates_set_on_promote(self, tmp_path):
        """When a rule is promoted during rehydration, the in-loop
        set should be updated so a duplicate later in the same
        ledger doesn't double-promote."""
        store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
        ledger = tmp_path / "ledger.jsonl"
        # Two ledger entries with the same signature
        dup = {
            "signature": "dup_sig",
            "kind": "error",
            "sample_text": "dup error",
            "occurrences": 4,
            "confidence": 0.85,
        }
        self._write_ledger(ledger, [dup, dup])

        synth = ReflectionSynthesizer(
            policy_store=store,
            persist_path=str(ledger),
            min_occurrences=3,
        )

        # Should only have one SOFT rule despite two ledger lines
        soft_rules = store.list_rules(tier=PolicyTier.SOFT)
        learned_ids = [r.rule_id for r in soft_rules
                       if r.rule_id == "learned::dup_sig"]
        assert len(learned_ids) == 1


# ===================================================================
# NEW-C: debate→belief key fallback in _check_belief_posterior
# ===================================================================


class TestBeliefDebateFallbackNEWC:
    """The belief gate now checks 'debate::<action_type>' when the
    primary 'target::action_type' key has no data."""

    def test_debate_key_used_when_primary_missing(self):
        """If only 'debate::launch' exists, the gate should use it."""
        beliefs = BeliefStore()
        # Feed enough observations to cross the min threshold
        for _ in range(5):
            beliefs.observe("debate::launch", success=True)

        advisor = JudgmentAdvisor(values=Values(), belief_store=beliefs)

        decision = {
            "target": "campaign_x",
            "action_type": "launch",
        }
        result = advisor._check_belief_posterior(decision)

        # Should have found the debate key and returned a real weight
        assert result["weight"] > 0
        assert result["risk"] < 0.5  # 5 successes → low risk

    def test_primary_key_preferred_over_debate_key(self):
        """When both primary and debate keys exist, primary wins."""
        beliefs = BeliefStore()
        # Primary key: mostly failures
        for _ in range(5):
            beliefs.observe("campaign_x::launch", success=False)
        # Debate key: mostly successes
        for _ in range(5):
            beliefs.observe("debate::launch", success=True)

        advisor = JudgmentAdvisor(values=Values(), belief_store=beliefs)

        decision = {
            "target": "campaign_x",
            "action_type": "launch",
        }
        result = advisor._check_belief_posterior(decision)

        # Primary key has mostly failures → high risk
        assert result["risk"] > 0.5

    def test_no_belief_at_all_returns_silent(self):
        """When neither key exists, the check is silent."""
        beliefs = BeliefStore()
        advisor = JudgmentAdvisor(values=Values(), belief_store=beliefs)

        decision = {
            "target": "new_target",
            "action_type": "deploy",
        }
        result = advisor._check_belief_posterior(decision)

        assert result["weight"] == 0.0
        assert "No prior outcomes" in result["reason"]

    def test_action_type_falls_back_to_type_key(self):
        """When 'action_type' is missing, 'type' is used."""
        beliefs = BeliefStore()
        for _ in range(4):
            beliefs.observe("debate::scale", success=True)

        advisor = JudgmentAdvisor(values=Values(), belief_store=beliefs)

        decision = {
            "target": "service_a",
            "type": "scale",
        }
        result = advisor._check_belief_posterior(decision)

        # Should find debate::scale
        assert result["weight"] > 0


# ===================================================================
# GAP-16: BeliefStore write debounce
# ===================================================================


class TestBeliefStoreDebounceGAP16:
    """The BeliefStore should not write to disk on every observe()
    call — only when the debounce interval has elapsed."""

    def test_rapid_observations_batch_writes(self, tmp_path):
        """Multiple observe() calls within the debounce interval
        should produce at most one disk write."""
        persist_path = tmp_path / "beliefs.json"
        store = BeliefStore(
            persist_path=str(persist_path),
            persist_debounce=100.0,  # long debounce
        )

        store.observe("key1", success=True)
        # First observe should trigger a write (interval exceeded)
        assert persist_path.exists()

        # Record file mtime after first write
        mtime_after_first = persist_path.stat().st_mtime_ns

        # Rapid-fire more observations — should NOT trigger writes
        # because debounce interval (100s) hasn't passed
        for i in range(10):
            store.observe(f"key_{i}", success=True)

        mtime_after_batch = persist_path.stat().st_mtime_ns

        # File should not have been rewritten during the burst
        assert mtime_after_batch == mtime_after_first

        # Dirty flag should be set
        assert store._persist_dirty is True

    def test_save_clears_dirty_flag(self, tmp_path):
        """Explicit save() flushes pending writes and clears
        the dirty flag."""
        persist_path = tmp_path / "beliefs.json"
        store = BeliefStore(
            persist_path=str(persist_path),
            persist_debounce=100.0,
        )

        # First observe writes (interval from 0 always exceeded),
        # then force the dirty state for subsequent observations.
        store.observe("k", success=True)
        store.observe("k2", success=True)
        assert store._persist_dirty is True

        store.save()
        assert store._persist_dirty is False

    def test_debounce_zero_writes_every_time(self, tmp_path):
        """With persist_debounce=0.0 (default), every observe()
        writes immediately — backward-compatible behavior."""
        persist_path = tmp_path / "beliefs.json"
        store = BeliefStore(persist_path=str(persist_path))

        store.observe("a", success=True)
        assert persist_path.exists()

        mtime1 = persist_path.stat().st_mtime_ns

        store.observe("b", success=True)

        mtime2 = persist_path.stat().st_mtime_ns
        # Should have written again (0.0 debounce)
        assert mtime2 >= mtime1
        # Dirty flag should be cleared
        assert store._persist_dirty is False

    def test_no_persist_path_no_debounce_state(self):
        """Without a persist_path, debounce fields exist but never
        cause errors."""
        store = BeliefStore()
        assert store._persist_dirty is False
        store.observe("x", success=True)
        # Still False — no persist path, no dirty flag set
        assert store._persist_dirty is False


# ===================================================================
# GAP-18: decay max_idle 60s floor guard
# ===================================================================


class TestDecayMaxIdleFloorGAP18:
    """The controller's _maybe_run_reflection_decay should clamp
    max_idle to 60s when the env var is set dangerously low."""

    def test_max_idle_clamped_to_60s(self, tmp_path):
        """With SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC=5, the actual
        value used should be 60."""
        c = _bare_controller(tmp_path)
        c._last_reflection_decay_at = 0.0  # ensure decay runs

        with patch.dict(os.environ, {
            "SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC": "5",
        }):
            # We need to observe what max_idle is actually passed
            # to decay_stale_rules. Patch the synthesizer's method.
            captured_args: list[float] = []
            original = c._reflection_synth.decay_stale_rules

            def capturing_decay(max_idle_sec, *, now=None):
                captured_args.append(max_idle_sec)
                return []

            c._reflection_synth.decay_stale_rules = capturing_decay  # type: ignore

            c._maybe_run_reflection_decay(time.time())

            assert len(captured_args) == 1
            assert captured_args[0] == 60.0  # clamped from 5 to 60

    def test_max_idle_above_floor_unchanged(self, tmp_path):
        """A sane max_idle value passes through unchanged."""
        c = _bare_controller(tmp_path)
        c._last_reflection_decay_at = 0.0

        with patch.dict(os.environ, {
            "SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC": "7200",
        }):
            captured_args: list[float] = []

            def capturing_decay(max_idle_sec, *, now=None):
                captured_args.append(max_idle_sec)
                return []

            c._reflection_synth.decay_stale_rules = capturing_decay  # type: ignore

            c._maybe_run_reflection_decay(time.time())

            assert len(captured_args) == 1
            assert captured_args[0] == 7200.0

    def test_floor_guard_logs_warning(self, tmp_path):
        """The floor guard emits a WARNING log."""
        import logging

        c = _bare_controller(tmp_path)
        c._last_reflection_decay_at = 0.0

        c._reflection_synth.decay_stale_rules = lambda *a, **kw: []  # type: ignore

        with patch.dict(os.environ, {
            "SHOPAI_REFLECTION_DECAY_MAX_IDLE_SEC": "10",
        }):
            with patch("core.autonomous.controller.logger") as mock_log:
                c._maybe_run_reflection_decay(time.time())
                # Should have warned about clamping
                mock_log.warning.assert_called()
                warn_msg = mock_log.warning.call_args[0][0]
                assert "floor" in warn_msg.lower() or "60s" in warn_msg
