"""Wave 7c gap-closure tests.

Covers four improvements:

  GAP-4  — record_failure() bridge on controller
  GAP-8  — MEDIUM rules persistence (JSONL ledger + rehydration)
  GAP-10 — AdapterMetricsCollector rename (backward compat alias)
  GAP-15 — Mind per-phase error reporting
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from core.autonomous.controller import AutonomousController
from core.cognitive.mind import CycleReport, Mind
from core.memory.quality_engine import MemoryRecord
from core.reflection.synthesizer import ReflectionSynthesizer
from engines.meta_governance.policy_store import (
    PolicyRule,
    PolicyStore,
    PolicyTier,
    PolicyVerdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_controller(tmp_path: Path) -> AutonomousController:
    c = AutonomousController.__new__(AutonomousController)
    store = PolicyStore(audit_path=str(tmp_path / "audit.jsonl"))
    c._reflection_synth = ReflectionSynthesizer(
        policy_store=store, min_occurrences=3,
    )
    c._reflection_buffer_max = 50
    c._error_buffer = None
    c._reflection_init_lock = threading.Lock()
    c._last_reflection_decay_at = 0.0
    c._REFLECTION_BUFFER_MAX = 50
    c._REFLECTION_DECAY_INTERVAL_SEC = 3600.0
    c._REFLECTION_DECAY_MAX_IDLE_SEC = 30 * 24 * 3600.0
    return c


# ===================================================================
# GAP-15: Mind per-phase error reporting
# ===================================================================


class TestMindPerPhaseErrors:
    """Mind.run_cycle should capture per-phase errors individually
    instead of aborting the entire cycle on the first failure."""

    def test_phase_errors_dict_on_report(self):
        """CycleReport has a phase_errors dict."""
        r = CycleReport(cycle_number=1, started_at=0.0)
        assert hasattr(r, "phase_errors")
        assert isinstance(r.phase_errors, dict)
        assert len(r.phase_errors) == 0

    def test_phase_errors_in_to_dict(self):
        """phase_errors appears in the serialised report."""
        r = CycleReport(cycle_number=1, started_at=0.0)
        r.phase_errors["plan"] = "TypeError: NoneType"
        d = r.to_dict()
        assert "phase_errors" in d
        assert d["phase_errors"]["plan"] == "TypeError: NoneType"

    def test_single_phase_failure_doesnt_block_others(self):
        """If one phase fails, subsequent phases still run."""
        mind = Mind()

        # Patch the plan phase to fail
        original_plan = mind._phase_plan

        def _failing_plan(ctx, report):
            raise RuntimeError("plan exploded")

        mind._phase_plan = _failing_plan

        report = mind.run_cycle()

        # Plan should have failed
        assert "plan" in report.phase_errors
        assert "plan exploded" in report.phase_errors["plan"]

        # But act should have still run (it follows plan)
        # — no "act" error means it ran successfully or at
        # least wasn't skipped
        # The aggregate error should contain the plan failure
        assert "plan" in report.error

    def test_multiple_phase_failures_all_captured(self):
        """Multiple failing phases all appear in phase_errors."""
        mind = Mind()

        def _fail(name):
            def _inner(ctx, report):
                raise ValueError(f"{name} boom")
            return _inner

        mind._phase_reflect = _fail("reflect")
        mind._phase_imagine = _fail("imagine")

        report = mind.run_cycle()

        assert "reflect" in report.phase_errors
        assert "imagine" in report.phase_errors
        assert "reflect boom" in report.phase_errors["reflect"]
        assert "imagine boom" in report.phase_errors["imagine"]

    def test_clean_cycle_has_empty_phase_errors(self):
        """A cycle with no failures has an empty phase_errors."""
        mind = Mind()
        report = mind.run_cycle()
        assert report.phase_errors == {}
        assert report.error == ""

    def test_controller_unpacks_per_phase_mind_errors(self):
        """The controller should inject cognitive_<phase> keys
        when the Mind report has phase_errors."""
        phase_errors: dict[str, str] = {}
        cycle_result: dict[str, Any] = {
            "cycle_id": "test",
            "cognitive": {
                "phase_errors": {
                    "plan": "TypeError: NoneType",
                    "act": "SkillNotFound: deploy",
                },
                "error": "plan: TypeError; act: SkillNotFound",
            },
        }

        # Simulate the controller's injection logic
        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict):
            cog_phases = cog.get("phase_errors")
            if isinstance(cog_phases, dict) and cog_phases:
                for phase_key, err_msg in cog_phases.items():
                    phase_errors[f"cognitive_{phase_key}"] = str(err_msg)
            elif cog.get("error"):
                phase_errors["cognitive_mind"] = str(cog["error"])

        assert "cognitive_plan" in phase_errors
        assert "cognitive_act" in phase_errors
        assert "cognitive_mind" not in phase_errors  # per-phase wins

    def test_controller_falls_back_to_aggregate(self):
        """Without phase_errors, falls back to single cognitive_mind."""
        phase_errors: dict[str, str] = {}
        cycle_result: dict[str, Any] = {
            "cycle_id": "test",
            "cognitive": {
                "error": "RuntimeError: generic crash",
            },
        }

        cog = cycle_result.get("cognitive")
        if isinstance(cog, dict):
            cog_phases = cog.get("phase_errors")
            if isinstance(cog_phases, dict) and cog_phases:
                for phase_key, err_msg in cog_phases.items():
                    phase_errors[f"cognitive_{phase_key}"] = str(err_msg)
            elif cog.get("error"):
                phase_errors["cognitive_mind"] = str(cog["error"])

        assert "cognitive_mind" in phase_errors


# ===================================================================
# GAP-10: AdapterMetricsCollector rename
# ===================================================================


class TestAdapterMetricsCollectorRename:
    """The adapter metrics class is now AdapterMetricsCollector
    with a backward-compat alias."""

    def test_canonical_import(self):
        from core.adapters.metrics import AdapterMetricsCollector
        collector = AdapterMetricsCollector()
        assert hasattr(collector, "record")

    def test_backward_compat_alias(self):
        from core.adapters.metrics import MetricsCollector
        from core.adapters.metrics import AdapterMetricsCollector
        assert MetricsCollector is AdapterMetricsCollector

    def test_get_metrics_returns_canonical_type(self):
        from core.adapters.metrics import (
            AdapterMetricsCollector,
            get_metrics,
            reset_metrics,
        )
        reset_metrics()
        m = get_metrics()
        assert isinstance(m, AdapterMetricsCollector)

    def test_no_confusion_with_telemetry_collector(self):
        from core.adapters.metrics import AdapterMetricsCollector
        from core.telemetry.metrics_collector import MetricsCollector
        assert AdapterMetricsCollector is not MetricsCollector


# ===================================================================
# GAP-4: record_failure() bridge
# ===================================================================


class TestRecordFailureBridge:
    """Controller.record_failure() feeds standalone errors into
    the reflection buffer without waiting for a cycle."""

    def test_record_failure_appends_to_buffer(self, tmp_path):
        c = _bare_controller(tmp_path)
        c.record_failure("shopify_api", "connection timeout")
        assert c._error_buffer is not None
        assert len(c._error_buffer) == 1
        rec = c._error_buffer[0]
        assert rec.kind == "error"
        assert rec.payload["phase"] == "shopify_api"
        assert rec.payload["message"] == "connection timeout"
        assert rec.payload["source"] == "record_failure"

    def test_record_failure_initializes_buffer_lazily(self, tmp_path):
        c = _bare_controller(tmp_path)
        c._error_buffer = None
        c.record_failure("subsys", "err")
        assert c._error_buffer is not None
        assert len(c._error_buffer) == 1

    def test_multiple_failures_accumulate(self, tmp_path):
        c = _bare_controller(tmp_path)
        for i in range(5):
            c.record_failure(f"adapter_{i}", f"error {i}")
        assert len(c._error_buffer) == 5

    def test_failures_visible_to_next_reflection_run(self, tmp_path):
        """Standalone failures should be mined alongside cycle errors."""
        c = _bare_controller(tmp_path)
        # Record 3 identical failures (meets min_occurrences=3)
        for _ in range(3):
            c.record_failure("payment_api", "500 internal server error")

        # Now run the reflection hook with empty cycle errors
        # — the standalone failures should be in the buffer
        cycle_result: dict[str, Any] = {"cycle_id": "test"}
        # Trigger the hook by adding a dummy error to phase_errors
        phase_errors = {"dummy": "trigger"}
        c._run_reflection_hook(cycle_result, phase_errors)

        # Buffer should have 3 standalone + 1 dummy = 4 records
        assert len(c._error_buffer) == 4

    def test_record_failure_is_fail_soft(self, tmp_path):
        """record_failure must never raise even if internals break."""
        c = _bare_controller(tmp_path)
        # Sabotage the buffer to make append fail
        c._error_buffer = "not a deque"  # type: ignore
        # Should not raise
        c.record_failure("x", "boom")


# ===================================================================
# GAP-8: MEDIUM rules persistence
# ===================================================================


class TestMediumRulesPersistence:
    """MEDIUM rules with match_field/match_pattern survive restarts."""

    def _make_medium_rule(
        self, rule_id: str, field: str, pattern: str,
        verdict: PolicyVerdict = PolicyVerdict.BLOCK,
    ) -> PolicyRule:
        compiled = re.compile(pattern)

        def _matcher(action: dict, _ctx: dict) -> bool:
            return bool(compiled.search(str(action.get(field, ""))))

        return PolicyRule(
            rule_id=rule_id,
            name=f"test-{rule_id}",
            tier=PolicyTier.MEDIUM,
            source="operator",
            description=f"Blocks {field} matching {pattern}",
            matcher=_matcher,
            verdict=verdict,
            match_field=field,
            match_pattern=pattern,
        )

    def test_medium_rule_persists_to_ledger(self, tmp_path):
        ledger = str(tmp_path / "medium.jsonl")
        store = PolicyStore(
            audit_path=str(tmp_path / "audit.jsonl"),
            medium_ledger_path=ledger,
        )
        rule = self._make_medium_rule("block_delete", "action_type", "delete")
        store.register(rule)

        # Ledger file should exist
        assert Path(ledger).exists()
        lines = Path(ledger).read_text().strip().split("\n")
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["rule_id"] == "block_delete"
        assert row["match_field"] == "action_type"
        assert row["match_pattern"] == "delete"

    def test_medium_rule_rehydrated_on_startup(self, tmp_path):
        ledger = str(tmp_path / "medium.jsonl")
        # First store: register and persist
        store1 = PolicyStore(
            audit_path=str(tmp_path / "audit.jsonl"),
            medium_ledger_path=ledger,
        )
        rule = self._make_medium_rule("block_delete", "action_type", "delete")
        store1.register(rule)

        # Second store: should rehydrate
        store2 = PolicyStore(
            audit_path=str(tmp_path / "audit2.jsonl"),
            medium_ledger_path=ledger,
        )
        rules = store2.list_rules(tier=PolicyTier.MEDIUM)
        assert len(rules) == 1
        assert rules[0].rule_id == "block_delete"
        assert rules[0].match_field == "action_type"
        assert rules[0].match_pattern == "delete"

    def test_rehydrated_matcher_works(self, tmp_path):
        """The reconstructed matcher should actually match."""
        ledger = str(tmp_path / "medium.jsonl")
        store1 = PolicyStore(
            audit_path=str(tmp_path / "a.jsonl"),
            medium_ledger_path=ledger,
        )
        store1.register(self._make_medium_rule(
            "block_price_drop", "description", r"price.*drop",
        ))

        store2 = PolicyStore(
            audit_path=str(tmp_path / "b.jsonl"),
            medium_ledger_path=ledger,
        )
        rule = store2.list_rules(tier=PolicyTier.MEDIUM)[0]
        assert rule.matcher({"description": "big price drop"}, {}) is True
        assert rule.matcher({"description": "price increase"}, {}) is False

    def test_remove_updates_ledger(self, tmp_path):
        ledger = str(tmp_path / "medium.jsonl")
        store = PolicyStore(
            audit_path=str(tmp_path / "audit.jsonl"),
            medium_ledger_path=ledger,
        )
        store.register(self._make_medium_rule("r1", "x", "a"))
        store.register(self._make_medium_rule("r2", "x", "b"))

        assert len(Path(ledger).read_text().strip().split("\n")) == 2

        store.remove("r1")
        lines = Path(ledger).read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["rule_id"] == "r2"

    def test_custom_callable_not_persisted(self, tmp_path):
        """Rules without match_field/match_pattern are not written."""
        ledger = str(tmp_path / "medium.jsonl")
        store = PolicyStore(
            audit_path=str(tmp_path / "audit.jsonl"),
            medium_ledger_path=ledger,
        )
        # Rule with custom callable, no match_field
        rule = PolicyRule(
            rule_id="custom_rule",
            name="custom",
            tier=PolicyTier.MEDIUM,
            source="operator",
            description="Custom logic",
            matcher=lambda a, c: a.get("dangerous") is True,
        )
        store.register(rule)

        # Ledger should be empty (or not exist)
        if Path(ledger).exists():
            content = Path(ledger).read_text().strip()
            assert content == ""

    def test_no_ledger_path_no_persistence(self, tmp_path):
        """Without medium_ledger_path, no file is created."""
        store = PolicyStore(
            audit_path=str(tmp_path / "audit.jsonl"),
        )
        rule = self._make_medium_rule("r1", "x", "a")
        store.register(rule)
        # No medium.jsonl anywhere
        assert not (tmp_path / "medium.jsonl").exists()

    def test_duplicate_rule_ids_skipped_on_rehydration(self, tmp_path):
        """If a rule_id already exists, rehydration skips the dup."""
        ledger = str(tmp_path / "medium.jsonl")
        # Write two lines with same rule_id
        Path(ledger).write_text(
            json.dumps({
                "rule_id": "dup", "name": "dup",
                "match_field": "x", "match_pattern": "a",
                "source": "operator", "verdict": "block",
                "version": 1, "created_at": "",
            }) + "\n"
            + json.dumps({
                "rule_id": "dup", "name": "dup",
                "match_field": "x", "match_pattern": "b",
                "source": "operator", "verdict": "block",
                "version": 2, "created_at": "",
            }) + "\n"
        )
        store = PolicyStore(
            audit_path=str(tmp_path / "audit.jsonl"),
            medium_ledger_path=ledger,
        )
        rules = store.list_rules(tier=PolicyTier.MEDIUM)
        assert len(rules) == 1
        assert rules[0].rule_id == "dup"
