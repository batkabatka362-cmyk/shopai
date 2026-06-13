"""Per-domain substrate-fire KPI computation (W847).

Reads the substrate_fire log + computes per-domain:
  - total outcomes in window
  - fire count
  - error count
  - success rate (fired / (fired + errors), excluding dry-runs)
  - avg duration_ms across fired outcomes

These KPIs feed the autonomy-status per-row column + an
upcoming engine-degradation alerter (W848+).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.automation.substrate_fire_log import (
    recent_substrate_fires,
)


@dataclass
class DomainFireKPI:
    domain: str
    total_outcomes: int = 0
    fired: int = 0
    dry_run: int = 0
    errors: int = 0
    avg_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """fired / (fired + errors), excluding dry-runs.
        Returns 1.0 when nothing happened (vacuously
        successful) so the metric stays operator-friendly."""
        actionable = self.fired + self.errors
        if actionable == 0:
            return 1.0
        return self.fired / actionable


@dataclass
class FireKPIReport:
    window_hours: float = 168.0
    store_id: str | None = None
    per_domain: list[DomainFireKPI] = field(
        default_factory=list,
    )

    def get(self, domain: str) -> DomainFireKPI | None:
        for k in self.per_domain:
            if k.domain == domain:
                return k
        return None


def compute_fire_kpis(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> FireKPIReport:
    """Aggregate substrate_fire log into per-domain KPIs."""
    report = FireKPIReport(
        window_hours=window_hours, store_id=store_id,
    )
    rows = recent_substrate_fires(
        window_hours=window_hours,
        store_id=store_id,
    )
    bucket: dict[str, dict] = {}
    for r in rows:
        d = r.get("domain") or ""
        if not d:
            continue
        b = bucket.setdefault(d, {
            "total": 0, "fired": 0, "dry_run": 0,
            "errors": 0, "duration_sum": 0.0,
            "duration_n": 0,
        })
        b["total"] += 1
        if r.get("invoked"):
            b["fired"] += 1
            try:
                dur = float(r.get("duration_ms") or 0.0)
            except (TypeError, ValueError):
                dur = 0.0
            b["duration_sum"] += dur
            b["duration_n"] += 1
        reason = r.get("reason") or ""
        if reason == "dry_run":
            b["dry_run"] += 1
        if reason in ("applier_error", "discoverer_error"):
            b["errors"] += 1
    for domain in sorted(bucket):
        b = bucket[domain]
        avg = (
            b["duration_sum"] / b["duration_n"]
            if b["duration_n"] else 0.0
        )
        report.per_domain.append(DomainFireKPI(
            domain=domain,
            total_outcomes=b["total"],
            fired=b["fired"],
            dry_run=b["dry_run"],
            errors=b["errors"],
            avg_duration_ms=avg,
        ))
    return report
