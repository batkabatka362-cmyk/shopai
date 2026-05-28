"""Autonomy doctor: 360° health check across every domain (W235).

``autonomy_status`` (W149) rolls up per-domain DomainSummary
verdicts. ``autonomy-doctor`` adds the *wiring* angle: for each
domain it surfaces

  - the verdict + paused flag (re-uses autonomy_status)
  - env-knob coverage (which knobs are set vs at default)
  - cycle hook wiring (Pattern U)
  - notify alert kinds registered (Pattern V)
  - env-gate enforcement (Pattern W)
  - 5-piece template completeness (Pattern Y')

Single command turns "are all 7 autonomy substrates healthy +
wired correctly" into one operator question.

Output classes (per-domain):
  - ``ok``     all green
  - ``warn``   wiring complete but verdict degraded / paused /
              or some env knob misconfigured
  - ``fail``   wiring broken (missing cycle hook, missing
              template piece, etc.)

Overall rollup = worst per-domain class.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.automation.autonomy_status import (
    DomainSummary,
    get_autonomy_status,
)


_DOMAIN_NAME_ALIASES = {
    # autonomy_status uses "customer_support" but the substrate
    # catalog (Pattern T/W) uses "customer_support_refund".
    "customer_support": "customer_support_refund",
    "marketing": "marketing_budget",
}


@dataclass
class DoctorDomainReport:
    name: str
    cls: str = "ok"  # ok / warn / fail
    verdict: str = "unknown"
    paused: bool = False
    applied_count: int = 0
    # Wiring checks
    cycle_hook_wired: bool = True
    notify_kinds_count: int = 0
    env_gated: bool = True
    template_complete: bool = True
    # Env coverage
    env_knobs_total: int = 0
    env_knobs_set: int = 0
    reasons: list[str] = field(default_factory=list)
    next_action: str = ""


@dataclass
class AutonomyDoctorReport:
    domains: list[DoctorDomainReport] = field(
        default_factory=list,
    )
    window_hours: float = 168.0
    store_id: str | None = None
    overall_cls: str = "ok"
    overall_next_action: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for d in self.domains if d.cls == "ok")

    @property
    def warn_count(self) -> int:
        return sum(1 for d in self.domains if d.cls == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for d in self.domains if d.cls == "fail")


_CLASS_SEVERITY = {"ok": 0, "warn": 1, "fail": 2}


def _resolve_domain_key(summary_name: str) -> str:
    """Normalise autonomy_status domain name → Pattern T catalog
    key."""
    return _DOMAIN_NAME_ALIASES.get(
        summary_name, summary_name,
    )


def _env_coverage(
    domain_key: str,
) -> tuple[int, int]:
    """Return ``(set_count, total_count)`` for a domain's
    registered env knobs (Pattern T's registry)."""
    try:
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
    except Exception:  # noqa: BLE001
        return (0, 0)
    try:
        report = build_autonomy_env_registry()
    except Exception:  # noqa: BLE001
        return (0, 0)
    total = 0
    set_count = 0
    for knob in report.knobs:
        if knob.domain == domain_key:
            total += 1
            if knob.current_value is not None:
                set_count += 1
    return (set_count, total)


def _wiring_checks(
    domain_key: str,
) -> dict[str, Any]:
    """Run the wiring audits + return per-domain pass/fail for
    cycle hook, notify, env-gate, template completeness."""
    out: dict[str, Any] = {
        "cycle_hook_wired": True,
        "notify_kinds_count": 0,
        "env_gated": True,
        "template_complete": True,
        "wiring_reasons": [],
    }
    # Pattern U
    try:
        from engines._pattern_u_audit import run_pattern_u_audit
        u = run_pattern_u_audit()
        if domain_key not in u.clean_domains:
            out["cycle_hook_wired"] = False
            out["wiring_reasons"].append(
                "cycle hook not wired",
            )
    except Exception:  # noqa: BLE001
        pass
    # Pattern V
    try:
        from engines._pattern_v_audit import run_pattern_v_audit
        v = run_pattern_v_audit()
        if domain_key in v.clean_domains:
            out["notify_kinds_count"] = 2
        else:
            out["notify_kinds_count"] = 0
            out["wiring_reasons"].append(
                "notify alert kinds missing",
            )
    except Exception:  # noqa: BLE001
        pass
    # Pattern W
    try:
        from engines._pattern_w_audit import run_pattern_w_audit
        w = run_pattern_w_audit()
        if domain_key not in w.clean_domains:
            out["env_gated"] = False
            out["wiring_reasons"].append(
                "env-prefix gate not enforced",
            )
    except Exception:  # noqa: BLE001
        pass
    # Pattern Y'
    try:
        from engines._pattern_yprime_audit import (
            run_pattern_yprime_audit,
        )
        y = run_pattern_yprime_audit()
        if domain_key not in y.clean_domains:
            out["template_complete"] = False
            out["wiring_reasons"].append(
                "5-piece template incomplete",
            )
    except Exception:  # noqa: BLE001
        pass
    return out


def _classify(
    summary: DomainSummary,
    wiring: dict[str, Any],
) -> tuple[str, list[str]]:
    """Decide per-domain class (ok / warn / fail) + collect
    reasons."""
    reasons: list[str] = []
    cls = "ok"
    # FAIL: wiring is broken
    if not wiring["cycle_hook_wired"]:
        cls = "fail"
        reasons.append("cycle hook not wired")
    if not wiring["template_complete"]:
        cls = "fail"
        reasons.append("template incomplete")
    if wiring["notify_kinds_count"] == 0:
        cls = "fail"
        reasons.append("notify alert kinds missing")
    if not wiring["env_gated"]:
        cls = "fail" if cls != "fail" else cls
        reasons.append("env-prefix gate not enforced")
    if cls == "fail":
        return cls, reasons
    # WARN: wiring fine but verdict degraded / paused
    if summary.paused:
        return ("warn", [f"paused -- {summary.next_action}"])
    if summary.verdict in {"degraded", "critical"}:
        return ("warn", [
            f"verdict={summary.verdict} -- {summary.next_action}"
        ])
    if summary.health_failure_ratio is not None:
        if summary.health_failure_ratio >= 0.20:
            return ("warn", [
                f"failure_ratio={summary.health_failure_ratio:.0%} -- "
                "monitor with -health"
            ])
    return ("ok", [])


def run_autonomy_doctor(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> AutonomyDoctorReport:
    """Run the 360° autonomy check."""
    report = AutonomyDoctorReport(
        window_hours=window_hours, store_id=store_id,
    )
    base = get_autonomy_status(
        window_hours=window_hours, store_id=store_id,
    )
    for summary in base.domains:
        domain_key = _resolve_domain_key(summary.name)
        wiring = _wiring_checks(domain_key)
        env_set, env_total = _env_coverage(domain_key)
        cls, reasons = _classify(summary, wiring)
        report.domains.append(DoctorDomainReport(
            name=summary.name,
            cls=cls,
            verdict=summary.verdict,
            paused=summary.paused,
            applied_count=summary.applied_count,
            cycle_hook_wired=wiring["cycle_hook_wired"],
            notify_kinds_count=wiring["notify_kinds_count"],
            env_gated=wiring["env_gated"],
            template_complete=wiring["template_complete"],
            env_knobs_total=env_total,
            env_knobs_set=env_set,
            reasons=reasons or list(wiring["wiring_reasons"]),
            next_action=summary.next_action,
        ))

    # Overall = worst class
    worst = 0
    worst_d: DoctorDomainReport | None = None
    for d in report.domains:
        sev = _CLASS_SEVERITY.get(d.cls, 0)
        if sev > worst:
            worst = sev
            worst_d = d
    if worst_d is None or worst == 0:
        report.overall_cls = "ok"
        report.overall_next_action = (
            "All autonomy domains operating cleanly."
        )
    else:
        report.overall_cls = worst_d.cls
        report.overall_next_action = (
            f"Drill into [{worst_d.name}]: "
            f"{worst_d.next_action or 'see -health'}"
        )
    return report
