"""Autonomy recommendations (W681).

Dashboards aggregate state, trends show direction, leaderboard
ranks domains. `autonomy-recommend` answers the proactive
question: "given the current state, what should the operator
do FIRST?"

Recommendation engine that scans 5 signal sources + emits
priority-ranked action items:

  1. PAUSED domains (severity=critical, priority=100)
  2. DEGRADED/CRITICAL health (severity=critical, priority=90)
  3. WIRING failures (severity=critical, priority=85)
  4. DORMANT domains (severity=warn, priority=50)
  5. UNTUNED env knobs (severity=info, priority=20)

Recommendation shape: {domain, action, command, severity,
priority, reason}. Sorted by priority desc.

Use case: operator runs `shopai autonomy-recommend` in the
morning + walks the top-3 to triage the empire. Or daily-brief
surfaces top-N inline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    domain: str
    action: str          # human-readable action label
    command: str         # specific shopai command to run
    severity: str = "info"   # critical / warn / info
    priority: int = 0    # higher = address first
    reason: str = ""


@dataclass
class RecommendReport:
    window_hours: float = 168.0
    store_id: str | None = None
    recommendations: list[Recommendation] = field(
        default_factory=list,
    )

    @property
    def critical_count(self) -> int:
        return sum(
            1 for r in self.recommendations
            if r.severity == "critical"
        )

    @property
    def warn_count(self) -> int:
        return sum(
            1 for r in self.recommendations
            if r.severity == "warn"
        )

    @property
    def info_count(self) -> int:
        return sum(
            1 for r in self.recommendations
            if r.severity == "info"
        )


def _domain_hyphen(domain: str) -> str:
    """Map autonomy_status names to CLI prefixes."""
    aliases = {
        "customer_support": "refund",
        "marketing": "marketing",
    }
    cli_prefix = aliases.get(domain, domain)
    return cli_prefix.replace("_", "-")


def _paused_recommendations(
    status_report,
) -> list[Recommendation]:
    """Highest priority: paused domains need operator review."""
    out: list[Recommendation] = []
    for d in status_report.domains:
        if not d.paused:
            continue
        cli = _domain_hyphen(d.name)
        out.append(Recommendation(
            domain=d.name,
            action="Review pause reason + resume if safe",
            command=f"shopai {cli}-status && shopai {cli}-resume",
            severity="critical",
            priority=100,
            reason=(
                f"auto-pause active "
                f"({d.next_action or 'no reason'})"
            ),
        ))
    return out


def _degraded_recommendations(
    status_report,
) -> list[Recommendation]:
    """Health verdict degraded / critical."""
    out: list[Recommendation] = []
    for d in status_report.domains:
        if d.paused:
            continue  # already covered by paused
        if d.verdict not in ("degraded", "critical"):
            continue
        cli = _domain_hyphen(d.name)
        out.append(Recommendation(
            domain=d.name,
            action="Run health analyzer + apply bridge",
            command=f"shopai {cli}-health --apply-bridge",
            severity="critical",
            priority=90,
            reason=(
                f"verdict={d.verdict}"
                + (
                    f" (failure ratio "
                    f"{d.health_failure_ratio:.0%})"
                    if d.health_failure_ratio is not None
                    else ""
                )
            ),
        ))
    return out


def _wiring_recommendations(
    doctor_report,
) -> list[Recommendation]:
    """Domains with wiring class=fail."""
    out: list[Recommendation] = []
    for d in doctor_report.domains:
        if d.cls != "fail":
            continue
        out.append(Recommendation(
            domain=d.name,
            action="Fix wiring (substrate integration broken)",
            command="shopai autonomy-doctor",
            severity="critical",
            priority=85,
            reason="; ".join(d.reasons) or "wiring failure",
        ))
    return out


def _dormant_recommendations(
    trends_report,
) -> list[Recommendation]:
    """Domains that were active recently but went silent."""
    out: list[Recommendation] = []
    for d in trends_report.domains:
        if d.verdict != "dormant":
            continue
        out.append(Recommendation(
            domain=d.domain,
            action=(
                "Check why activity dropped to 0 this "
                "window"
            ),
            command=(
                f"shopai autonomy-domain {d.domain} "
                "--window-hours 168"
            ),
            severity="warn",
            priority=50,
            reason=(
                f"previous window: {d.previous_applied} "
                "applied; current: 0"
            ),
        ))
    return out


def _untuned_env_recommendations(
    status_report,
) -> list[Recommendation]:
    """Domains using all default env knobs -- candidate for
    operator tuning."""
    out: list[Recommendation] = []
    try:
        from engines._pattern_t_audit import (
            build_autonomy_env_registry,
        )
        registry = build_autonomy_env_registry()
    except Exception:  # noqa: BLE001
        return out

    # Count knobs per domain (substrate key -> set_count)
    per_domain_set: dict[str, int] = {}
    per_domain_total: dict[str, int] = {}
    for knob in registry.knobs:
        per_domain_total[knob.domain] = (
            per_domain_total.get(knob.domain, 0) + 1
        )
        if knob.current_value is not None:
            per_domain_set[knob.domain] = (
                per_domain_set.get(knob.domain, 0) + 1
            )

    # Recommend for domains that are quiet (no fires) AND
    # have no env tuning. These are the candidates for first-
    # time operator setup.
    for d in status_report.domains:
        if d.verdict != "quiet":
            continue
        # Resolve autonomy_status name to substrate key
        from core.automation.autonomy_doctor import (
            _resolve_domain_key,
        )
        sub_key = _resolve_domain_key(d.name)
        total = per_domain_total.get(sub_key, 0)
        set_count = per_domain_set.get(sub_key, 0)
        if total == 0 or set_count > 0:
            continue
        out.append(Recommendation(
            domain=d.name,
            action="Tune env knobs before first cycle fire",
            command=(
                f"shopai autonomy-env --domain {sub_key}"
            ),
            severity="info",
            priority=20,
            reason=(
                f"{total} env knob(s) all at default; "
                "domain is quiet"
            ),
        ))
    return out


def run_autonomy_recommend(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> RecommendReport:
    """Build a priority-ranked recommendation list."""
    report = RecommendReport(
        window_hours=window_hours, store_id=store_id,
    )

    # Source 1: autonomy_status (paused + degraded + verdict)
    try:
        from core.automation.autonomy_status import (
            get_autonomy_status,
        )
        status = get_autonomy_status(
            window_hours=window_hours, store_id=store_id,
        )
        report.recommendations.extend(
            _paused_recommendations(status),
        )
        report.recommendations.extend(
            _degraded_recommendations(status),
        )
        report.recommendations.extend(
            _untuned_env_recommendations(status),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autonomy_recommend: status probe failed: %s",
            exc,
        )

    # Source 2: autonomy_doctor (wiring failures)
    try:
        from core.automation.autonomy_doctor import (
            run_autonomy_doctor,
        )
        doctor = run_autonomy_doctor(
            window_hours=window_hours, store_id=store_id,
        )
        report.recommendations.extend(
            _wiring_recommendations(doctor),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autonomy_recommend: doctor probe failed: %s",
            exc,
        )

    # Source 3: autonomy_trends (dormant)
    try:
        from core.automation.autonomy_trends import (
            run_autonomy_trends,
        )
        trends = run_autonomy_trends(
            window_hours=window_hours, store_id=store_id,
        )
        report.recommendations.extend(
            _dormant_recommendations(trends),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autonomy_recommend: trends probe failed: %s",
            exc,
        )

    # Sort by priority desc, then by severity (critical first)
    severity_rank = {"critical": 0, "warn": 1, "info": 2}
    report.recommendations.sort(
        key=lambda r: (
            -r.priority,
            severity_rank.get(r.severity, 3),
        ),
    )

    return report
