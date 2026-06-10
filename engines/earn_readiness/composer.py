"""Cross-check composer: am I ready to fire the first cycle?

Aggregates 5 independent signals:

  1. api_inventory  -- adapter credentials configured at minimum
                        per ROLE category
  2. go_live        -- pre-flight check (13 sub-checks)
  3. autonomy_doctor-- 10 production autonomy domains health
  4. cycle_history  -- has the cycle ever fired?
  5. wired_engines  -- at least one Phase 7 engine wired

Each signal returns its own verdict; the composer maps
them into a 3-tier verdict (ready / warn / not_ready) +
ranks the top blockers. Operator sees one screen:

  shopai earn-readiness

  [OK ]  Brain configured            (OPENAI_API_KEY set)
  [OK ]  Ad channels configured      (Meta Ads)
  [WRN]  Email category              (Klaviyo recommended)
  [BAD]  No cycle yet                (shopai cycle run --yes)
  ...
  Overall: WARN  -- 2 blockers + 1 advisory

Pure read-only. No Pattern J guard needed -- doesn't
write to disk; consults configured state via the
respective probe modules.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CheckSlice:
    """One sub-check's verdict slice."""
    name: str
    cls: str       # "ok" / "warn" / "fail"
    headline: str
    detail: str = ""
    fix: str = ""

    @property
    def severity_rank(self) -> int:
        return {"ok": 0, "warn": 1, "fail": 2}.get(self.cls, 0)


@dataclass
class EarnReadinessReport:
    """The full composer output."""
    overall_verdict: str = "ready"   # ready / warn / not_ready
    checks: list[CheckSlice] = field(default_factory=list)
    headline: str = ""
    next_action: str = ""
    # Per-slice counts for quick dashboard binding
    ok_count: int = 0
    warn_count: int = 0
    fail_count: int = 0

    @property
    def top_blockers(self) -> list[CheckSlice]:
        """Failing checks sorted; operator's punch list."""
        return [c for c in self.checks if c.cls == "fail"]

    @property
    def warnings(self) -> list[CheckSlice]:
        return [c for c in self.checks if c.cls == "warn"]


# ── Individual probes ─────────────────────────────────────


def _check_api_inventory() -> CheckSlice:
    """Adapter credentials at-minimum per category."""
    try:
        from engines.api_inventory.inventory import (
            build_inventory,
        )
        report = build_inventory()
    except Exception as exc:  # noqa: BLE001
        logger.debug("api_inventory probe raised: %s", exc)
        return CheckSlice(
            name="api_inventory",
            cls="warn",
            headline=f"probe failed: {exc}",
            fix="Check engines.api_inventory imports",
        )

    incomplete = report.incomplete_categories
    if not incomplete:
        return CheckSlice(
            name="api_inventory",
            cls="ok",
            headline=(
                f"{report.configured_count}/"
                f"{report.total_aliases} adapter "
                "alias(es) set; every required category at "
                "minimum"
            ),
        )

    titles = [c.title.split(" --")[0] for c in incomplete[:3]]
    return CheckSlice(
        name="api_inventory",
        cls="fail",
        headline=(
            f"{len(incomplete)} categor(y/ies) below "
            f"minimum. Top: {', '.join(titles)}"
        ),
        fix="shopai api-status --missing-only",
    )


def _check_go_live() -> CheckSlice:
    """Pre-flight gate. Failures here block cycle launch."""
    try:
        from engines._go_live_check import run_go_live_check
        results = run_go_live_check()
    except Exception as exc:  # noqa: BLE001
        logger.debug("go_live probe raised: %s", exc)
        return CheckSlice(
            name="go_live",
            cls="warn",
            headline=f"probe failed: {exc}",
            fix="Investigate engines._go_live_check",
        )

    fails = [r for r in results if r.status == "fail"]
    warns = [r for r in results if r.status == "warn"]

    if fails:
        names = ", ".join(r.name for r in fails[:3])
        return CheckSlice(
            name="go_live",
            cls="fail",
            headline=(
                f"{len(fails)} fail(s), {len(warns)} warn(s). "
                f"Failing: {names}"
            ),
            fix="shopai go-live",
        )

    if warns:
        names = ", ".join(r.name for r in warns[:3])
        return CheckSlice(
            name="go_live",
            cls="warn",
            headline=(
                f"{len(warns)} warn(s). First: {names}"
            ),
            fix="shopai go-live",
        )

    return CheckSlice(
        name="go_live",
        cls="ok",
        headline=f"{len(results)} pre-flight checks pass",
    )


def _check_autonomy_doctor() -> CheckSlice:
    """10 production autonomy domains health."""
    try:
        from core.automation.autonomy_doctor import (
            run_autonomy_doctor,
        )
        report = run_autonomy_doctor()
    except Exception as exc:  # noqa: BLE001
        logger.debug("autonomy_doctor probe raised: %s", exc)
        return CheckSlice(
            name="autonomy_doctor",
            cls="warn",
            headline=f"probe failed: {exc}",
            fix="Investigate core.automation.autonomy_doctor",
        )

    if report.fail_count > 0:
        return CheckSlice(
            name="autonomy_doctor",
            cls="fail",
            headline=(
                f"{report.fail_count} domain(s) failing, "
                f"{report.warn_count} warning, "
                f"{report.ok_count} ok"
            ),
            fix="shopai autonomy-doctor",
        )

    if report.warn_count > 0:
        return CheckSlice(
            name="autonomy_doctor",
            cls="warn",
            headline=(
                f"{report.warn_count} domain(s) warning, "
                f"{report.ok_count} ok"
            ),
            fix="shopai autonomy-doctor",
        )

    return CheckSlice(
        name="autonomy_doctor",
        cls="ok",
        headline=(
            f"All {report.ok_count} autonomy domain(s) ok"
        ),
    )


def _check_cycle_history() -> CheckSlice:
    """Has the first cycle ever fired?"""
    try:
        from engines._cycle_history import last_run
        last = last_run()
    except Exception as exc:  # noqa: BLE001
        logger.debug("cycle_history probe raised: %s", exc)
        return CheckSlice(
            name="cycle_history",
            cls="warn",
            headline=f"probe failed: {exc}",
            fix="Investigate engines._cycle_history",
        )

    if last is None:
        return CheckSlice(
            name="cycle_history",
            cls="fail",
            headline="No cycle has ever run",
            fix="shopai cycle run --yes",
        )

    # Check age
    started = getattr(last, "started_at", None)
    if started is None:
        return CheckSlice(
            name="cycle_history",
            cls="warn",
            headline="Last cycle has no timestamp",
        )

    try:
        age_h = max(
            0.0, (time.time() - float(started)) / 3600.0,
        )
    except (TypeError, ValueError):
        return CheckSlice(
            name="cycle_history",
            cls="warn",
            headline="Last cycle timestamp unparseable",
        )

    if age_h <= 26.0:
        return CheckSlice(
            name="cycle_history",
            cls="ok",
            headline=f"Last cycle {age_h:.1f}h ago (fresh)",
        )

    if age_h <= 168.0:
        return CheckSlice(
            name="cycle_history",
            cls="warn",
            headline=f"Last cycle {age_h:.1f}h ago (stale)",
            fix="shopai cycle run --yes  (or cron schedule)",
        )

    return CheckSlice(
        name="cycle_history",
        cls="fail",
        headline=f"Last cycle {age_h:.1f}h ago (> 1 week)",
        fix="shopai cycle schedule",
    )


def _check_wired_engines() -> CheckSlice:
    """At least one Phase 7 engine wired with apply_* flag."""
    try:
        from engines._writeback_audit import (
            audit_writeback_coverage,
        )
        wb = audit_writeback_coverage("engines")
        wired = [
            s.name for s in wb.engines
            if s.status == "wired"
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("wired_engines probe raised: %s", exc)
        return CheckSlice(
            name="wired_engines",
            cls="warn",
            headline=f"probe failed: {exc}",
            fix="Investigate engines._writeback_audit",
        )

    if len(wired) == 0:
        return CheckSlice(
            name="wired_engines",
            cls="fail",
            headline="0 engines wired (Phase 7)",
            fix="See engines/loyalty for the wireup template",
        )
    if len(wired) < 5:
        return CheckSlice(
            name="wired_engines",
            cls="warn",
            headline=(
                f"{len(wired)} engine(s) wired (low; "
                "consider wiring more before going live)"
            ),
            fix="See engines/loyalty for the wireup template",
        )

    return CheckSlice(
        name="wired_engines",
        cls="ok",
        headline=f"{len(wired)} engine(s) wired (Phase 7)",
    )


# ── Composer ──────────────────────────────────────────────


def _compose_verdict(checks: list[CheckSlice]) -> str:
    """Map per-check verdicts to an overall verdict."""
    has_fail = any(c.cls == "fail" for c in checks)
    has_warn = any(c.cls == "warn" for c in checks)
    if has_fail:
        return "not_ready"
    if has_warn:
        return "warn"
    return "ready"


def _compose_next_action(
    verdict: str, checks: list[CheckSlice],
) -> str:
    if verdict == "ready":
        return (
            "All checks green -- safe to fire "
            "shopai cycle run --yes"
        )
    # Surface the FIRST failing check's fix; failing
    # ranks above warning by severity.
    sorted_checks = sorted(
        checks,
        key=lambda c: (-c.severity_rank, c.name),
    )
    for c in sorted_checks:
        if c.cls in ("fail", "warn") and c.fix:
            return c.fix
    return "Address the blocker(s) above"


def build_readiness() -> EarnReadinessReport:
    """Build the full readiness report. Runs every probe;
    on individual probe failure the slice is marked 'warn'
    so the composer's overall verdict downgrades gracefully
    rather than crashing."""
    checks = [
        _check_api_inventory(),
        _check_wired_engines(),
        _check_go_live(),
        _check_autonomy_doctor(),
        _check_cycle_history(),
    ]
    report = EarnReadinessReport(
        checks=checks,
        overall_verdict=_compose_verdict(checks),
    )
    report.ok_count = sum(1 for c in checks if c.cls == "ok")
    report.warn_count = sum(1 for c in checks if c.cls == "warn")
    report.fail_count = sum(1 for c in checks if c.cls == "fail")
    if report.overall_verdict == "ready":
        report.headline = (
            f"READY TO LAUNCH -- "
            f"{report.ok_count}/{len(checks)} checks green"
        )
    elif report.overall_verdict == "warn":
        report.headline = (
            f"READY WITH WARNINGS -- "
            f"{report.ok_count} green, "
            f"{report.warn_count} warn"
        )
    else:
        report.headline = (
            f"NOT READY -- "
            f"{report.fail_count} blocker(s), "
            f"{report.warn_count} warn, "
            f"{report.ok_count} green"
        )
    report.next_action = _compose_next_action(
        report.overall_verdict, checks,
    )
    return report
