"""Autonomy trends (W581): per-domain activity trend across
two adjacent time windows.

`shopai autonomy-history` shows the chronological event
timeline. `autonomy-trends` answers the routine ops question:
"which domains have grown / shrunk in activity this week vs
last week, and which are flat?"

Implementation: for each of the 9 autonomy domains, fetch
events in two adjacent windows:
  - current window: now - window_hours .. now
  - previous window: now - 2*window_hours .. now - window_hours

Compute applied / skipped / total counts in each + delta +
verdict (rising / falling / flat / new / dormant).

Used by:
  - operator routine ops: "which domains need attention this
    week"
  - empire dashboard one-liner ("3 rising, 1 falling")
  - LLM agent context: "domain X grew 4x; investigate"

Deliberately read-only -- no calls to pause / resume /
bridges.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

logger = logging.getLogger(__name__)


# Reuse autonomy_history's per-domain catalog so trends + history
# stay in sync. autonomy_history._DOMAIN_LOGS is the source of truth.


@dataclass
class DomainTrend:
    domain: str
    current_total: int = 0
    current_applied: int = 0
    current_skipped: int = 0
    previous_total: int = 0
    previous_applied: int = 0
    previous_skipped: int = 0
    delta_total: int = 0
    delta_applied: int = 0
    verdict: str = "flat"  # rising / falling / flat / new / dormant
    delta_pct: float = 0.0  # signed % change in applied count


@dataclass
class TrendReport:
    window_hours: float
    domains: list[DomainTrend] = field(default_factory=list)
    rising_count: int = 0
    falling_count: int = 0
    flat_count: int = 0
    new_count: int = 0
    dormant_count: int = 0
    overall_summary: str = ""


_RISING_THRESHOLD_PCT = 25.0      # > +25% applied = rising
_FALLING_THRESHOLD_PCT = -25.0    # < -25% applied = falling


def _classify_verdict(
    cur_applied: int, prev_applied: int,
) -> tuple[str, float]:
    """Return (verdict, delta_pct)."""
    if cur_applied == 0 and prev_applied == 0:
        return ("flat", 0.0)
    if cur_applied > 0 and prev_applied == 0:
        return ("new", 0.0)
    if cur_applied == 0 and prev_applied > 0:
        return ("dormant", -100.0)
    # Both > 0: compute % change
    pct = (
        (cur_applied - prev_applied) * 100.0
        / max(prev_applied, 1)
    )
    if pct > _RISING_THRESHOLD_PCT:
        return ("rising", pct)
    if pct < _FALLING_THRESHOLD_PCT:
        return ("falling", pct)
    return ("flat", pct)


def _count_window(
    pkg: str, log_modname: str, fn_name: str,
    window_hours: float,
    store_id: str | None,
) -> tuple[int, int, int]:
    """Return (total, applied, skipped) for one domain's log."""
    try:
        mod = import_module(f"engines.{pkg}.{log_modname}")
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "autonomy_trends: import %s.%s failed: %s",
            pkg, log_modname, exc,
        )
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
            # Phase 11.A's recent_refunds doesn't accept store_id
            rows = fn(window_hours=window_hours)
    except Exception:  # noqa: BLE001
        return (0, 0, 0)
    total = len(rows)
    applied = sum(
        1 for r in rows if r.get("applied") is True
    )
    return (total, applied, total - applied)


def _count_previous_window(
    pkg: str, log_modname: str, fn_name: str,
    window_hours: float, store_id: str | None,
) -> tuple[int, int, int]:
    """Count events in the PREVIOUS window
    (now - 2W .. now - W). Implementation trick: fetch all
    events in 2W window, subtract the current-W counts."""
    cur = _count_window(
        pkg, log_modname, fn_name, window_hours, store_id,
    )
    full = _count_window(
        pkg, log_modname, fn_name, window_hours * 2,
        store_id,
    )
    # full = current + previous; previous = full - current
    return (
        max(full[0] - cur[0], 0),
        max(full[1] - cur[1], 0),
        max(full[2] - cur[2], 0),
    )


def run_autonomy_trends(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> TrendReport:
    """Compute per-domain trend across two adjacent windows."""
    from core.automation.autonomy_history import _DOMAIN_LOGS

    report = TrendReport(window_hours=window_hours)

    for short, pkg, log_modname, fn_name in _DOMAIN_LOGS:
        ct = _count_window(
            pkg, log_modname, fn_name,
            window_hours, store_id,
        )
        pt = _count_previous_window(
            pkg, log_modname, fn_name,
            window_hours, store_id,
        )
        verdict, pct = _classify_verdict(ct[1], pt[1])
        trend = DomainTrend(
            domain=short,
            current_total=ct[0],
            current_applied=ct[1],
            current_skipped=ct[2],
            previous_total=pt[0],
            previous_applied=pt[1],
            previous_skipped=pt[2],
            delta_total=ct[0] - pt[0],
            delta_applied=ct[1] - pt[1],
            verdict=verdict,
            delta_pct=pct,
        )
        report.domains.append(trend)

    # Aggregate
    counts: dict[str, int] = {
        "rising": 0, "falling": 0, "flat": 0,
        "new": 0, "dormant": 0,
    }
    for d in report.domains:
        counts[d.verdict] = counts.get(d.verdict, 0) + 1
    report.rising_count = counts["rising"]
    report.falling_count = counts["falling"]
    report.flat_count = counts["flat"]
    report.new_count = counts["new"]
    report.dormant_count = counts["dormant"]

    # One-line summary
    parts = []
    if report.rising_count:
        parts.append(f"{report.rising_count} rising")
    if report.falling_count:
        parts.append(f"{report.falling_count} falling")
    if report.new_count:
        parts.append(f"{report.new_count} new")
    if report.dormant_count:
        parts.append(f"{report.dormant_count} dormant")
    if report.flat_count:
        parts.append(f"{report.flat_count} flat")
    report.overall_summary = (
        ", ".join(parts) if parts else "all quiet"
    )

    return report
