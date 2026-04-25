"""Live health trend — rolling digest across doctor probes,
autopilot cycles, and the learning ledger.

PATH_TO_T2.md §2 P1-C: ``shopai live-health`` gives the owner
a "is today worse than yesterday" read without trawling logs.
It combines three sources already available at T0:

  * ``core.readiness.doctor.run()`` — live probe of every
    upstream (Shopify, Meta, fal, vault, moby). Single
    snapshot.
  * ``data/autopilot_loop.log`` — per-cycle CycleSummary
    rollups (mode / launches / successful / duration / error).
    Tail the last N.
  * ``core.learning.feedback_store`` — per-engine trend
    (improving / stable / declining) across recorded outcomes.

The output has three shapes:

  * ``current`` — right-now doctor verdict (ready / degraded /
    blocked) and the feedback-store summary.
  * ``recent_cycles`` — N most recent cycle rollups with
    error flag.
  * ``verdict`` — aggregate label ("healthy" / "degrading" /
    "needs_attention") derived from all three sources via
    deterministic rules.

Pure stdlib. No LLM. Read-only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DEFAULT_LOG = "data/autopilot_loop.log"


@dataclass
class HealthTrend:
    verdict: str  # "healthy" | "degrading" | "needs_attention" | "unknown"
    reasons: list[str] = field(default_factory=list)
    doctor_ok: bool = True
    doctor_critical_failures: int = 0
    doctor_warnings: int = 0
    cycles_considered: int = 0
    cycles_with_error: int = 0
    cycles_live_mode: int = 0
    engines_improving: int = 0
    engines_stable: int = 0
    engines_declining: int = 0
    recent_cycles: list[dict[str, Any]] = field(
        default_factory=list,
    )
    engine_trends: dict[str, str] = field(
        default_factory=dict,
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "doctor": {
                "ok": self.doctor_ok,
                "critical_failures": (
                    self.doctor_critical_failures
                ),
                "warnings": self.doctor_warnings,
            },
            "cycles": {
                "considered": self.cycles_considered,
                "with_error": self.cycles_with_error,
                "live_mode": self.cycles_live_mode,
                "recent": list(self.recent_cycles),
            },
            "engines": {
                "improving": self.engines_improving,
                "stable": self.engines_stable,
                "declining": self.engines_declining,
                "trends": dict(self.engine_trends),
            },
        }


def _tail_cycles(
    log_path: str, limit: int,
) -> list[dict[str, Any]]:
    """Return the last ``limit`` parsed cycle summaries from
    the autopilot log. Missing / malformed log → empty list."""
    p = Path(log_path)
    if not p.exists():
        return []
    cycles: list[dict[str, Any]] = []
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                cycles.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return cycles[-int(limit):]


def _read_engine_trends(
    feedback_store: Any,
) -> dict[str, str]:
    """Return {engine_name: trend} for every engine with
    recorded feedback."""
    try:
        stats = feedback_store.get_all_stats()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for name, data in stats.items():
        trend = data.get("trend") if isinstance(
            data, dict,
        ) else None
        if trend:
            out[str(name)] = str(trend)
    return out


def _decide(
    doctor_report: Any,
    cycles: list[dict[str, Any]],
    engine_trends: dict[str, str],
) -> tuple[str, list[str]]:
    """Deterministic verdict from three sources."""
    reasons: list[str] = []

    doctor_ok = bool(getattr(doctor_report, "ok", True))
    crit = int(getattr(
        doctor_report, "critical_failures", 0,
    ))

    cycles_with_error = sum(
        1 for c in cycles if c.get("error")
    )
    declining = sum(
        1 for t in engine_trends.values()
        if t == "declining"
    )

    if crit > 0:
        reasons.append(
            f"doctor reports {crit} critical failures",
        )
    elif not doctor_ok:
        reasons.append("doctor reports warnings")

    if cycles and cycles_with_error > len(cycles) / 3:
        reasons.append(
            f"{cycles_with_error} of "
            f"{len(cycles)} recent cycles errored",
        )

    if declining > 0:
        reasons.append(
            f"{declining} engines show declining trend",
        )

    # Rules:
    # - crit > 0 OR doctor not ok → needs_attention
    # - >33% cycles with error OR any declining engine → degrading
    # - everything else → healthy
    # - no cycles + no engines + doctor unknown → unknown
    if crit > 0 or not doctor_ok:
        return ("needs_attention", reasons)
    if not cycles and not engine_trends:
        return ("unknown", reasons or [
            "no cycles + no engine feedback yet",
        ])
    if (
        (cycles and cycles_with_error > len(cycles) / 3)
        or declining > 0
    ):
        return ("degrading", reasons)
    return ("healthy", reasons or ["all signals green"])


def compute_live_health(
    *,
    doctor_runner: Any = None,
    feedback_store: Any = None,
    log_path: str = _DEFAULT_LOG,
    cycles_limit: int = 20,
) -> HealthTrend:
    """Main entry — pulls a fresh doctor report + the last N
    cycle summaries + per-engine feedback trends and fuses
    into a single verdict.

    Dependency-injected so tests supply fakes for all three
    data sources.
    """
    # Doctor
    if doctor_runner is None:
        from core.readiness.doctor import run as _run_doctor
        doctor_report = _run_doctor()
    else:
        doctor_report = doctor_runner()

    cycles = _tail_cycles(log_path, cycles_limit)

    # Feedback store
    if feedback_store is None:
        try:
            from core.learning.feedback_store import (
                get_feedback_store,
            )
            feedback_store = get_feedback_store()
        except Exception:  # noqa: BLE001
            feedback_store = None
    engine_trends = (
        _read_engine_trends(feedback_store)
        if feedback_store is not None else {}
    )

    verdict, reasons = _decide(
        doctor_report, cycles, engine_trends,
    )

    # Per-trend counters
    improving = sum(
        1 for t in engine_trends.values()
        if t == "improving"
    )
    stable = sum(
        1 for t in engine_trends.values()
        if t == "stable"
    )
    declining = sum(
        1 for t in engine_trends.values()
        if t == "declining"
    )

    return HealthTrend(
        verdict=verdict,
        reasons=reasons,
        doctor_ok=bool(getattr(
            doctor_report, "ok", True,
        )),
        doctor_critical_failures=int(getattr(
            doctor_report, "critical_failures", 0,
        )),
        doctor_warnings=int(getattr(
            doctor_report, "warnings", 0,
        )),
        cycles_considered=len(cycles),
        cycles_with_error=sum(
            1 for c in cycles if c.get("error")
        ),
        cycles_live_mode=sum(
            1 for c in cycles
            if c.get("mode") == "live"
        ),
        engines_improving=improving,
        engines_stable=stable,
        engines_declining=declining,
        recent_cycles=cycles[-5:],
        engine_trends=engine_trends,
    )
