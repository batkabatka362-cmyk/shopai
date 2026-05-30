"""Week-over-week substrate-fire KPI trend (W855).

Computes per-domain KPI deltas between the CURRENT window
(now - W hours to now) and the PRIOR window (now - 2W to
now - W). Surfaces rising / falling / stable verdicts so the
operator can spot trends before they cross alert thresholds.

Same window-pairs strategy as ``shopai autonomy-trends`` (the
existing W581 trend CLI for autonomy activity counts).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.automation.substrate_fire_kpi import (
    DomainFireKPI,
    compute_fire_kpis,
)


@dataclass
class DomainFireTrend:
    domain: str
    current_success_rate: float = 1.0
    previous_success_rate: float = 1.0
    delta_success_rate: float = 0.0
    current_fired: int = 0
    previous_fired: int = 0
    current_errors: int = 0
    previous_errors: int = 0
    verdict: str = "flat"  # rising | falling | flat | new | dormant


@dataclass
class FireTrendReport:
    window_hours: float = 168.0
    store_id: str | None = None
    per_domain: list[DomainFireTrend] = field(
        default_factory=list,
    )

    @property
    def rising_count(self) -> int:
        return sum(
            1 for d in self.per_domain
            if d.verdict == "rising"
        )

    @property
    def falling_count(self) -> int:
        return sum(
            1 for d in self.per_domain
            if d.verdict == "falling"
        )

    @property
    def flat_count(self) -> int:
        return sum(
            1 for d in self.per_domain
            if d.verdict == "flat"
        )


_SIGNIFICANT_DELTA = 0.10  # 10 pct points


def _verdict(
    cur: DomainFireKPI | None,
    prev: DomainFireKPI | None,
) -> str:
    """Decide trend verdict per domain."""
    if cur is None and prev is None:
        return "flat"
    if cur is None or cur.fired + cur.errors == 0:
        if prev is not None and prev.fired + prev.errors > 0:
            return "dormant"
        return "flat"
    if prev is None or prev.fired + prev.errors == 0:
        if cur.fired + cur.errors > 0:
            return "new"
        return "flat"
    delta = cur.success_rate - prev.success_rate
    if delta >= _SIGNIFICANT_DELTA:
        return "rising"
    if delta <= -_SIGNIFICANT_DELTA:
        return "falling"
    return "flat"


def compute_fire_trend(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> FireTrendReport:
    """Build per-domain trend report. ``window_hours`` is the
    SHORTER of the two periods (e.g. 168 = 7 days each =
    14-day total scan)."""
    report = FireTrendReport(
        window_hours=window_hours, store_id=store_id,
    )

    # Fetch 2W window then subtract W to derive prior bucket.
    # Use the existing compute_fire_kpis with extended window.
    full = compute_fire_kpis(
        window_hours=window_hours * 2.0,
        store_id=store_id,
    )
    cur_only = compute_fire_kpis(
        window_hours=window_hours,
        store_id=store_id,
    )

    # Build a (domain -> prev KPI) map by subtracting cur from full
    cur_by_dom: dict[str, DomainFireKPI] = {
        k.domain: k for k in cur_only.per_domain
    }
    full_by_dom: dict[str, DomainFireKPI] = {
        k.domain: k for k in full.per_domain
    }
    all_domains = sorted(
        set(cur_by_dom) | set(full_by_dom),
    )

    for domain in all_domains:
        cur = cur_by_dom.get(domain)
        full_kpi = full_by_dom.get(domain)
        prev = None
        if full_kpi is not None:
            # Derive prev = full - cur for fired + errors. For
            # success_rate the meaningful approach is to compute
            # prev's rate from prev's counts directly.
            cur_fired = cur.fired if cur else 0
            cur_errors = cur.errors if cur else 0
            prev_fired = max(
                0, full_kpi.fired - cur_fired,
            )
            prev_errors = max(
                0, full_kpi.errors - cur_errors,
            )
            prev = DomainFireKPI(
                domain=domain,
                fired=prev_fired,
                errors=prev_errors,
            )
        trend = DomainFireTrend(
            domain=domain,
            current_success_rate=(
                cur.success_rate if cur else 1.0
            ),
            previous_success_rate=(
                prev.success_rate if prev else 1.0
            ),
            current_fired=cur.fired if cur else 0,
            previous_fired=prev.fired if prev else 0,
            current_errors=cur.errors if cur else 0,
            previous_errors=prev.errors if prev else 0,
        )
        trend.delta_success_rate = (
            trend.current_success_rate
            - trend.previous_success_rate
        )
        trend.verdict = _verdict(cur, prev)
        report.per_domain.append(trend)

    return report
