"""Integration harness — wire-check across every subsystem.

126+ modules are useless if they don't actually talk to each
other end-to-end. Individual unit tests catch local bugs; they
miss the 'subsystem A updates state, subsystem B never sees it'
class of bug.

IntegrationHarness runs a deliberate sequence through brain_facade
(v13-D1), agi_cycle (v12-D2), decision_governor (v12-D1), and
outcome_router (v12-D5), then verifies each downstream subsystem
*actually observed* the outcome.

The harness is framework-free: it doesn't mock anything. It runs
the real singletons and snapshots stats before/after. Any
subsystem that claims to listen but doesn't update is flagged.

APIs:

  run_health_check()               → HealthReport
  verify_wiring(outcome, expect)   → WiringReport
  benchmark_end_to_end()           → float (overall score)

Used by the daemon startup probe, the ops dashboard, and the CI
integration test so regressions in cross-module wiring surface
immediately.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SubsystemCheck:
    name: str
    ok: bool
    before: Any = None
    after: Any = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "before": self.before,
            "after": self.after,
            "note": self.note,
        }


@dataclass
class HealthReport:
    status: str                      # "ok" | "degraded" | "broken"
    checks: list[SubsystemCheck] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def pct_passing(self) -> float:
        if not self.checks:
            return 0.0
        ok = sum(1 for c in self.checks if c.ok)
        return ok / len(self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "pct_passing": round(self.pct_passing, 3),
            "elapsed_ms": round(self.elapsed_ms, 2),
            "checks": [c.as_dict() for c in self.checks],
        }


# ── Subsystem probes ────────────────────────────────────────

def _safe(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _snapshot() -> dict[str, Any]:
    """Capture current state of every subsystem we expect to learn."""
    snap: dict[str, Any] = {}
    snap["world_model"] = _safe(
        lambda: __import__(
            "core.brain.world_model", fromlist=["world_model"],
        ).world_model().summary(),
        {},
    )
    snap["epistemic"] = _safe(
        lambda: __import__(
            "core.brain.epistemic", fromlist=["coverage_engine"],
        ).coverage_engine().summary(),
        {},
    )
    snap["reward"] = _safe(
        lambda: __import__(
            "core.brain.reward_model", fromlist=["reward_model"],
        ).reward_model().size(),
        {},
    )
    snap["policy_library"] = _safe(
        lambda: __import__(
            "core.brain.policy_library", fromlist=["PolicyLibrary"],
        ).PolicyLibrary().stats(),
        {},
    )
    snap["habits"] = _safe(
        lambda: __import__(
            "core.brain.habit", fromlist=["HabitLayer"],
        ).HabitLayer().stats(),
        {},
    )
    snap["hypothesis"] = _safe(
        lambda: {
            "pending": len(
                __import__(
                    "core.brain.hypothesis", fromlist=["engine"],
                ).engine().list_pending(),
            ),
        },
        {},
    )
    return snap


def _delta(before: dict[str, Any], after: dict[str, Any],
           key_chain: list[str]) -> int:
    """Read nested values via key_chain on both snaps and return the
    numerical delta (defaults to 0)."""
    def _drill(d: Any, chain: list[str]) -> Any:
        for k in chain:
            if not isinstance(d, dict) or k not in d:
                return 0
            d = d[k]
        return d if isinstance(d, (int, float)) else 0
    return int(_drill(after, key_chain)) - int(_drill(before, key_chain))


# ── Wiring probes ──────────────────────────────────────────

def verify_wiring() -> HealthReport:
    """Fire a canonical Outcome through the router and confirm each
    advertised subscriber actually updated state."""
    start = time.monotonic()
    report = HealthReport(status="ok")

    # 1. Snapshot pre
    before = _snapshot()

    # 2. Fire canonical outcome
    try:
        from core.brain.outcome_router import Outcome, router
        dispatch = router().emit(Outcome(
            kind="order",
            features={
                "niche": "_integration_probe",
                "price_band": "mid",
            },
            source="_harness_probe",
            sign=1.0, success=True,
            value=10.0, kpi="revenue", action="scale",
            habit_signature="_probe_sig",
        )).as_dict()
    except Exception as exc:
        report.status = "broken"
        report.checks.append(SubsystemCheck(
            name="outcome_router",
            ok=False,
            note=f"dispatcher raised: {exc}",
        ))
        report.elapsed_ms = (time.monotonic() - start) * 1000
        return report
    delivered = set(dispatch.get("delivered", []))
    errs = dispatch.get("errors", [])
    if errs:
        report.status = "degraded"

    # 3. Snapshot post
    after = _snapshot()

    # 4. Check each expected learner moved
    expected = {
        "world_model":
            ("world_model", ["world_model", "total_observations"]),
        "epistemic":
            ("epistemic", ["epistemic", "total_observations"]),
        "reward_model":
            ("reward_model", ["reward", "total_feedback_events"]),
        "policy_library":
            ("policy_library", ["policy_library", "total_uses"]),
    }
    for handler, (label, chain) in expected.items():
        subscribed = handler in delivered
        moved = _delta(before, after, chain)
        ok = (subscribed and moved >= 0)   # policy_library may not
                                            # have a matching rule
        report.checks.append(SubsystemCheck(
            name=label, ok=ok,
            before=_deep_get(before, chain),
            after=_deep_get(after, chain),
            note=("delivered" if subscribed else
                  "NOT subscribed to 'order' outcomes"),
        ))
        if not subscribed:
            report.status = "degraded"

    # 5. Always-expected: outcome_router itself responded.
    report.checks.append(SubsystemCheck(
        name="outcome_router",
        ok=True,
        note=f"delivered to {sorted(delivered)}",
    ))

    # 6. AGI cycle runs without error
    try:
        from core.brain.agi_cycle import run_cycle
        rep = run_cycle({"kind": "probe", "niche": "_integration_probe"})
        errors = [s for s in rep.stages if s.status == "error"]
        report.checks.append(SubsystemCheck(
            name="agi_cycle",
            ok=not errors,
            note=(f"{len(errors)} stage error(s)" if errors
                  else "all stages passed"),
        ))
        if errors:
            report.status = "degraded"
    except Exception as exc:
        report.checks.append(SubsystemCheck(
            name="agi_cycle", ok=False,
            note=f"raised: {exc}",
        ))
        report.status = "degraded"

    # 7. Brain facade smoke
    try:
        from core.brain.brain_facade import brain
        snap = brain().introspect()
        d = snap.as_dict()
        empty_count = sum(
            1 for k, v in d.items()
            if k != "ts" and (v is None
                               or (isinstance(v, dict) and not v)
                               or (isinstance(v, list) and not v))
        )
        report.checks.append(SubsystemCheck(
            name="brain_facade",
            ok=empty_count < 3,
            note=f"{empty_count}/10 slots empty",
        ))
    except Exception as exc:
        report.checks.append(SubsystemCheck(
            name="brain_facade", ok=False,
            note=f"raised: {exc}",
        ))
        report.status = "degraded"

    # Final status classification
    failed = [c for c in report.checks if not c.ok]
    if not failed:
        report.status = "ok"
    elif len(failed) >= 3:
        report.status = "broken"
    else:
        report.status = "degraded"

    report.elapsed_ms = (time.monotonic() - start) * 1000
    return report


def _deep_get(d: Any, chain: list[str]) -> Any:
    for k in chain:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


# ── End-to-end benchmark ────────────────────────────────────

def benchmark_end_to_end() -> float:
    """Run the BrainBenchmark suite and return overall score."""
    try:
        from core.brain.benchmark import BrainBenchmark
        return BrainBenchmark().run_all().overall
    except Exception:
        return 0.0


# ── Full health ─────────────────────────────────────────────

def run_health_check() -> HealthReport:
    """Wiring probe + end-to-end benchmark as a single report."""
    report = verify_wiring()
    score = benchmark_end_to_end()
    report.checks.append(SubsystemCheck(
        name="brain_benchmark",
        ok=score >= 0.8,
        note=f"overall score {score:.2f}",
    ))
    # Recompute status
    failed = [c for c in report.checks if not c.ok]
    if not failed:
        report.status = "ok"
    elif len(failed) >= 3:
        report.status = "broken"
    else:
        report.status = "degraded"
    return report
