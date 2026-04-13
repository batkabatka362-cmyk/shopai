"""Wave 4 #4: Mind post-cycle cognitive audit + dispatcher observability.

The Wave 3 #1 commit wired a CognitiveDispatcher onto Mind but
nothing in run_cycle ever dispatched through it, so the MBTI
dispatch surface was technically present but operationally
dark — call_counts were all zero, recent history was empty.

Wave 4 #4 adds two things:

* A bounded-history observability layer on CognitiveDispatcher
  (counts, error counts, recent ring buffer, stats())
* A post-cycle audit hook on Mind that dispatches Si (self-model
  snapshot) and Ni (consolidation dry-run) — two idempotent,
  side-effect-free calls — so every cycle leaves a trace. The
  observability counters now reflect real production activity.

Plus: Mind.cognitive_report() as a single operator-facing entry
point for the observability snapshot.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.cognitive.functions import (
    CognitiveDispatcher,
    CognitiveFunction,
    DispatchResult,
)
from core.cognitive.mind import Mind


# ---------------------------------------------------------------------------
# Helpers — minimal stubs so Mind has SelfModel + Consolidation wired
# ---------------------------------------------------------------------------


class _StubSelfModel:
    def __init__(self) -> None:
        self.snapshot_calls = 0

    def snapshot(self) -> dict[str, Any]:
        self.snapshot_calls += 1
        return {"strengths": [], "weaknesses": [], "gaps": []}

    def strengths(self, top_n: int = 3):
        return []

    def weaknesses(self, top_n: int = 3):
        return []

    def knowledge_gaps(self, top_n: int = 3):
        return []


class _StubConsolidation:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []

    def run(self, *, dry_run: bool = False) -> dict[str, Any]:
        self.run_calls.append({"dry_run": dry_run})
        return {"consolidated": 0, "dry_run": dry_run}


# ---------------------------------------------------------------------------
# CognitiveDispatcher observability
# ---------------------------------------------------------------------------


def test_dispatcher_counts_successful_dispatches():
    disp = CognitiveDispatcher()
    disp.register(CognitiveFunction.Ti, lambda ctx: "ok")
    for _ in range(3):
        disp.dispatch(CognitiveFunction.Ti, {})
    stats = disp.stats()
    assert stats["counts"]["Ti"] == 3
    assert stats["errors"] == {}
    assert stats["total"] == 3
    assert all(entry["status"] == "ok" for entry in stats["recent"])


def test_dispatcher_counts_skipped_when_no_handler():
    disp = CognitiveDispatcher()
    result = disp.dispatch(CognitiveFunction.Te, {})
    assert result.skipped is True
    stats = disp.stats()
    assert stats["counts"]["Te"] == 1
    assert stats["errors"] == {}
    assert stats["recent"][-1]["status"] == "skipped"


def test_dispatcher_counts_errors():
    disp = CognitiveDispatcher()
    def _boom(ctx):
        raise RuntimeError("oops")
    disp.register(CognitiveFunction.Fi, _boom)
    disp.dispatch(CognitiveFunction.Fi, {})
    stats = disp.stats()
    assert stats["counts"]["Fi"] == 1
    assert stats["errors"]["Fi"] == 1
    assert stats["recent"][-1]["status"] == "error"


def test_dispatcher_history_is_bounded():
    disp = CognitiveDispatcher(history_size=5)
    disp.register(CognitiveFunction.Ti, lambda ctx: None)
    for _ in range(20):
        disp.dispatch(CognitiveFunction.Ti, {})
    stats = disp.stats()
    assert len(stats["recent"]) == 5
    assert stats["counts"]["Ti"] == 20  # counts ignore the history cap


def test_dispatcher_reset_stats_clears_counts_but_keeps_handlers():
    disp = CognitiveDispatcher()
    handler_called = {"n": 0}
    def _h(ctx):
        handler_called["n"] += 1
        return 1
    disp.register(CognitiveFunction.Ti, _h)
    disp.dispatch(CognitiveFunction.Ti, {})
    disp.reset_stats()
    stats = disp.stats()
    assert stats["counts"] == {}
    assert stats["recent"] == []
    # handler is still registered
    assert disp.has(CognitiveFunction.Ti)
    disp.dispatch(CognitiveFunction.Ti, {})
    assert handler_called["n"] == 2


def test_dispatcher_stats_registered_list_preserved():
    disp = CognitiveDispatcher()
    disp.register(CognitiveFunction.Ti, lambda c: 1)
    disp.register(CognitiveFunction.Te, lambda c: 2)
    stats = disp.stats()
    assert set(stats["registered"]) == {"Ti", "Te"}


# ---------------------------------------------------------------------------
# Mind post-cycle audit hook
# ---------------------------------------------------------------------------


def test_run_cycle_emits_si_and_ni_dispatches():
    mind = Mind(
        self_model=_StubSelfModel(),
        consolidation=_StubConsolidation(),
    )
    mind.run_cycle()
    stats = mind.cognitive_dispatcher().stats()
    # Si + Ni should each have been dispatched exactly once
    assert stats["counts"].get("Si") == 1
    assert stats["counts"].get("Ni") == 1
    # both should be ok (real stub handlers)
    assert stats["errors"] == {}
    recent_functions = [entry["function"] for entry in stats["recent"]]
    assert "Si" in recent_functions
    assert "Ni" in recent_functions


def test_run_cycle_audit_passes_dry_run_to_consolidation():
    con = _StubConsolidation()
    mind = Mind(self_model=_StubSelfModel(), consolidation=con)
    mind.run_cycle()
    # Consolidation should have been called with dry_run=True by
    # the audit, even if the legacy _phase_consolidate also ran
    assert any(c["dry_run"] is True for c in con.run_calls)


def test_multiple_cycles_accumulate_audit_counts():
    mind = Mind(
        self_model=_StubSelfModel(),
        consolidation=_StubConsolidation(),
    )
    mind.run_cycle()
    mind.run_cycle()
    mind.run_cycle()
    stats = mind.cognitive_dispatcher().stats()
    assert stats["counts"]["Si"] == 3
    assert stats["counts"]["Ni"] == 3


def test_audit_dispatches_skipped_when_subsystems_missing():
    mind = Mind()  # no self_model, no consolidation
    mind.run_cycle()
    stats = mind.cognitive_dispatcher().stats()
    # Both dispatches still logged, but as skipped (no handler)
    assert stats["counts"].get("Si") == 1
    assert stats["counts"].get("Ni") == 1
    skipped = [e for e in stats["recent"] if e["status"] == "skipped"]
    skipped_fns = {e["function"] for e in skipped}
    assert {"Si", "Ni"}.issubset(skipped_fns)


def test_audit_absorbs_handler_crash():
    class _BoomSelfModel(_StubSelfModel):
        def snapshot(self):
            raise RuntimeError("self model down")

    mind = Mind(
        self_model=_BoomSelfModel(),
        consolidation=_StubConsolidation(),
    )
    # Must not raise
    report = mind.run_cycle()
    stats = mind.cognitive_dispatcher().stats()
    assert stats["errors"].get("Si") == 1
    # Ni still succeeds
    assert stats["errors"].get("Ni") is None
    # Cycle itself didn't error
    assert report.error == ""


# ---------------------------------------------------------------------------
# cognitive_report() convenience wrapper
# ---------------------------------------------------------------------------


def test_cognitive_report_includes_cycle_count():
    mind = Mind(
        self_model=_StubSelfModel(),
        consolidation=_StubConsolidation(),
    )
    mind.run_cycle()
    mind.run_cycle()
    report = mind.cognitive_report()
    assert report["cycles_run"] == 2
    assert "counts" in report
    assert "recent" in report
    assert "registered" in report


def test_cognitive_report_before_any_cycle():
    mind = Mind()
    report = mind.cognitive_report()
    assert report["cycles_run"] == 0
    assert report["total"] == 0
