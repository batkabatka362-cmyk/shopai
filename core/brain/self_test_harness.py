"""Self-test harness — the brain runs its own health tests.

integration_harness.py already verifies wiring at import time. This
module is its run-time companion: periodically the brain should
ask itself "am I still sane?" by running a suite of small,
registered checks and reporting a health report.

A ``HealthCheck`` is:

    name
    category        ("memory" | "consistency" | "performance" | "misc")
    run             — callable returning CheckOutcome
    severity        — info / warning / critical
    description

Each check runs independently; an exception is caught and marked as
failed. The report aggregates status counts and per-check outcomes.

Pure stdlib, deterministic given the check functions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.self_test_harness")


Severity = Literal["info", "warning", "critical"]
Category = Literal["memory", "consistency", "performance", "misc"]


@dataclass
class CheckOutcome:
    ok: bool
    note: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "note": self.note,
            "metrics": dict(self.metrics),
        }


@dataclass
class HealthCheck:
    name: str
    category: Category
    run: Callable[[], CheckOutcome]
    severity: Severity = "warning"
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("HealthCheck.name required")
        if self.category not in (
            "memory", "consistency", "performance", "misc",
        ):
            raise ValueError(
                "category must be memory/consistency/"
                "performance/misc",
            )
        if self.severity not in ("info", "warning", "critical"):
            raise ValueError(
                "severity must be info/warning/critical",
            )


@dataclass
class CheckResult:
    name: str
    category: Category
    severity: Severity
    ok: bool
    note: str
    elapsed_ms: float
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "severity": self.severity,
            "ok": self.ok,
            "note": self.note,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "metrics": dict(self.metrics),
        }


@dataclass
class HealthReport:
    ts: float
    ok_count: int
    failed_count: int
    critical_count: int
    results: list[CheckResult] = field(default_factory=list)

    @property
    def overall_ok(self) -> bool:
        return self.critical_count == 0 and self.failed_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "ok_count": self.ok_count,
            "failed_count": self.failed_count,
            "critical_count": self.critical_count,
            "overall_ok": self.overall_ok,
            "results": [r.as_dict() for r in self.results],
        }


class SelfTestHarness:
    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    # ── Registration ─────────────────────────────────────

    def register(
        self, check: HealthCheck, overwrite: bool = False,
    ) -> None:
        if check.name in self._checks and not overwrite:
            raise ValueError(
                f"check {check.name!r} already registered",
            )
        self._checks[check.name] = check

    def unregister(self, name: str) -> bool:
        return self._checks.pop(name, None) is not None

    def checks(self) -> list[HealthCheck]:
        return list(self._checks.values())

    def filter_by_category(
        self, category: Category,
    ) -> list[HealthCheck]:
        return [c for c in self._checks.values() if c.category == category]

    # ── Run ──────────────────────────────────────────────

    def _run_one(self, check: HealthCheck) -> CheckResult:
        started = time.monotonic()
        try:
            outcome = check.run()
            if not isinstance(outcome, CheckOutcome):
                return CheckResult(
                    name=check.name,
                    category=check.category,
                    severity=check.severity,
                    ok=False,
                    note="check did not return CheckOutcome",
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                )
            return CheckResult(
                name=check.name,
                category=check.category,
                severity=check.severity,
                ok=bool(outcome.ok),
                note=outcome.note,
                elapsed_ms=(time.monotonic() - started) * 1000.0,
                metrics=dict(outcome.metrics),
            )
        except Exception as exc:
            logger.debug(
                "check %s raised: %s", check.name, exc,
            )
            return CheckResult(
                name=check.name,
                category=check.category,
                severity=check.severity,
                ok=False,
                note=f"raised: {exc}",
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )

    def run_all(
        self,
        *,
        category: Category | None = None,
    ) -> HealthReport:
        checks = (
            self.filter_by_category(category)
            if category is not None
            else list(self._checks.values())
        )
        results: list[CheckResult] = []
        ok_count = 0
        failed_count = 0
        critical_count = 0
        for c in checks:
            r = self._run_one(c)
            results.append(r)
            if r.ok:
                ok_count += 1
            else:
                failed_count += 1
                if r.severity == "critical":
                    critical_count += 1
        return HealthReport(
            ts=time.time(),
            ok_count=ok_count,
            failed_count=failed_count,
            critical_count=critical_count,
            results=results,
        )

    def stats(self) -> dict[str, Any]:
        by_cat: dict[str, int] = {}
        for c in self._checks.values():
            by_cat[c.category] = by_cat.get(c.category, 0) + 1
        return {
            "registered_checks": len(self._checks),
            "by_category": by_cat,
        }


# ── Canonical built-in checks ─────────────────────────────

def memory_nonzero_check(min_records: int = 1) -> HealthCheck:
    """Simple example: verify the experience recorder has something."""
    def _run() -> CheckOutcome:
        try:
            from core.brain.experience_recorder import stats
            s = stats()
            total = int(s.get("total", 0))
        except Exception as exc:
            return CheckOutcome(
                ok=False, note=f"stats unavailable: {exc}",
            )
        ok = total >= min_records
        return CheckOutcome(
            ok=ok,
            note=(
                f"{total} experience records"
                if ok
                else f"experience record count {total} < {min_records}"
            ),
            metrics={"total": total},
        )

    return HealthCheck(
        name="experience_nonzero",
        category="memory",
        run=_run,
        severity="warning",
        description="Experience recorder has at least min_records entries",
    )


def consistency_check(
    name: str,
    predicate: Callable[[], bool],
    *,
    severity: Severity = "warning",
    description: str = "",
) -> HealthCheck:
    """Wrap a simple predicate as a HealthCheck."""
    def _run() -> CheckOutcome:
        try:
            ok = bool(predicate())
        except Exception as exc:
            return CheckOutcome(
                ok=False,
                note=f"predicate raised: {exc}",
            )
        return CheckOutcome(
            ok=ok,
            note="predicate held" if ok else "predicate failed",
        )

    return HealthCheck(
        name=name,
        category="consistency",
        run=_run,
        severity=severity,
        description=description,
    )
