"""Autonomy leaderboard (W616): rank domains by activity +
success rate.

`shopai autonomy-trends` shows direction (rising / falling)
across two windows. `autonomy-leaderboard` is the cross-section
view at a single window: rank all 9 domains by recent activity
+ success rate + failure ratio so operator can spot:
  - top earners ("which domain fired the most this week")
  - underperformers ("which domain has the highest failure
    ratio")
  - quiet domains ("which are idle and might need attention")

Three sort modes:
  - applied (default): most active first
  - failure_ratio:    most-failing first
  - success_rate:     highest success rate first
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import import_module

logger = logging.getLogger(__name__)


@dataclass
class LeaderEntry:
    domain: str
    total: int = 0
    applied: int = 0
    skipped: int = 0
    success_rate: float = 0.0    # applied / total (0.0 if total=0)
    failure_ratio: float = 0.0   # skipped / total
    paused: bool = False
    health_verdict: str = "unknown"


@dataclass
class LeaderboardReport:
    window_hours: float
    store_id: str | None = None
    sort_by: str = "applied"
    entries: list[LeaderEntry] = field(default_factory=list)
    total_applied_fleet: int = 0
    total_skipped_fleet: int = 0
    active_count: int = 0     # domains with total > 0
    paused_count: int = 0
    most_active: str = ""
    highest_failure: str = ""


def _count_window(
    pkg: str, log_modname: str, fn_name: str,
    window_hours: float, store_id: str | None,
) -> tuple[int, int, int]:
    """Return (total, applied, skipped)."""
    try:
        mod = import_module(f"engines.{pkg}.{log_modname}")
    except Exception:  # noqa: BLE001
        return (0, 0, 0)
    fn = getattr(mod, fn_name, None)
    if fn is None:
        return (0, 0, 0)
    try:
        try:
            rows = fn(
                window_hours=window_hours, store_id=store_id,
            )
        except TypeError:
            rows = fn(window_hours=window_hours)
    except Exception:  # noqa: BLE001
        return (0, 0, 0)
    total = len(rows)
    applied = sum(
        1 for r in rows if r.get("applied") is True
    )
    return (total, applied, total - applied)


def _domain_health(
    pkg: str, health_modname: str, fn_name: str,
) -> str:
    """Best-effort health verdict via analyze_X_health()."""
    try:
        mod = import_module(
            f"engines.{pkg}.{health_modname}",
        )
        fn = getattr(mod, fn_name, None)
        if fn is None:
            return "unknown"
        r = fn()
        return getattr(r, "verdict", "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _domain_paused(
    pkg: str, state_modname: str,
) -> bool:
    try:
        mod = import_module(f"engines.{pkg}.{state_modname}")
        is_paused = getattr(mod, "is_paused", None)
        if is_paused is None:
            return False
        return bool(is_paused())
    except Exception:  # noqa: BLE001
        return False


def _sort_key(entry: LeaderEntry, mode: str):
    if mode == "failure_ratio":
        # Highest failure ratio first; tiebreak by activity
        return (-entry.failure_ratio, -entry.applied)
    if mode == "success_rate":
        # Highest success rate first; tiebreak by activity
        return (-entry.success_rate, -entry.applied)
    # default = "applied"
    return (-entry.applied, -entry.total)


def run_autonomy_leaderboard(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
    sort_by: str = "applied",
) -> LeaderboardReport:
    """Rank all autonomy domains for the operator's
    leaderboard view."""
    from core.automation.autonomy_history import _DOMAIN_LOGS

    # Per-domain health module names (mirrors autonomy_bench).
    health_catalog = {
        "refund": ("returns_management", "refund_health",
                   "analyze_refund_health"),
        "marketing": ("roas_guardrails", "budget_health",
                      "analyze_budget_health"),
        "fulfillment": ("fulfillment_autonomy",
                        "fulfillment_health",
                        "analyze_fulfillment_health"),
        "inventory": ("inventory_autonomy",
                      "inventory_health",
                      "analyze_inventory_health"),
        "cleanup": ("discount_cleanup_autonomy",
                    "cleanup_health",
                    "analyze_cleanup_health"),
        "followup": ("order_followup_autonomy",
                     "followup_health",
                     "analyze_followup_health"),
        "seo": ("product_seo_autonomy", "seo_health",
                "analyze_seo_health"),
        "outreach": ("customer_outreach_autonomy",
                     "outreach_health",
                     "analyze_customer_outreach_health"),
        "quality": ("catalog_quality_autonomy",
                    "quality_health",
                    "analyze_catalog_quality_health"),
    }
    state_catalog = {
        "refund": ("returns_management", "refund_state"),
        "marketing": ("roas_guardrails", "budget_state"),
        "fulfillment": ("fulfillment_autonomy",
                        "fulfillment_state"),
        "inventory": ("inventory_autonomy",
                      "inventory_state"),
        "cleanup": ("discount_cleanup_autonomy",
                    "cleanup_state"),
        "followup": ("order_followup_autonomy",
                     "followup_state"),
        "seo": ("product_seo_autonomy", "seo_state"),
        "outreach": ("customer_outreach_autonomy",
                     "outreach_state"),
        "quality": ("catalog_quality_autonomy",
                    "quality_state"),
    }

    report = LeaderboardReport(
        window_hours=window_hours,
        store_id=store_id,
        sort_by=sort_by,
    )

    for short, pkg, log_modname, fn_name in _DOMAIN_LOGS:
        total, applied, skipped = _count_window(
            pkg, log_modname, fn_name,
            window_hours, store_id,
        )
        success_rate = (
            applied / total if total > 0 else 0.0
        )
        failure_ratio = (
            skipped / total if total > 0 else 0.0
        )
        # Health + paused
        if short in health_catalog:
            hpkg, hmod, hfn = health_catalog[short]
            health = _domain_health(hpkg, hmod, hfn)
        else:
            health = "unknown"
        if short in state_catalog:
            spkg, smod = state_catalog[short]
            paused = _domain_paused(spkg, smod)
        else:
            paused = False
        entry = LeaderEntry(
            domain=short,
            total=total,
            applied=applied,
            skipped=skipped,
            success_rate=success_rate,
            failure_ratio=failure_ratio,
            paused=paused,
            health_verdict=health,
        )
        report.entries.append(entry)
        report.total_applied_fleet += applied
        report.total_skipped_fleet += skipped
        if total > 0:
            report.active_count += 1
        if paused:
            report.paused_count += 1

    # Sort + pick winners
    report.entries.sort(key=lambda e: _sort_key(e, sort_by))
    if report.entries:
        report.most_active = report.entries[0].domain if (
            sort_by == "applied"
        ) else max(
            report.entries, key=lambda e: e.applied,
        ).domain
        # highest failure: only count entries with activity
        active = [e for e in report.entries if e.total > 0]
        if active:
            report.highest_failure = max(
                active, key=lambda e: e.failure_ratio,
            ).domain

    return report
