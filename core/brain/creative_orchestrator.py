"""Creative A/B orchestrator.

CreativeStep (Sprint v1) generates three ad variants per launch.
But without a feedback loop, all three stay live forever — the
system never learns which angle converts and never rotates in a
fresh variant when one stalls.

This module closes the loop:

  1. INGEST — every order webhook carries an ``ad_variant_id`` (stamped
     by the Meta Ads pixel). We already tag order memories with
     ``launch:<id>``; extend the schema so ``variant:<id>`` is tagged
     too. Per-variant impressions + spend come from Meta Insights
     snapshots (``category=ad_insight`` memory events).
  2. EVALUATE — for every (launch, variant) pair, compute CTR, CVR,
     CPA, ROAS. Use Bayesian posterior with a Beta(α=1, β=1) prior so
     small samples don't falsely promote.
  3. RANK — rank variants by lower 95 % credible bound on ROAS;
     winners are promoted (``verdict=promote``), losers pruned
     (``verdict=prune``) when their upper bound is below the winner's
     lower bound (standard Bayesian A/B stopping rule).
  4. REFRESH — for every pruned slot, emit a ``next_variant`` advisory
     so the daemon's brain can regenerate a replacement with a fresh
     angle (hook_angle not yet used in that launch).

Pure statistics, no LLM. LLM regeneration happens in the daemon's
advisory→action path; this module only produces the signal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


_PRIOR_A = 1.0
_PRIOR_B = 1.0
_Z_95 = 1.96             # 95 % two-sided bound
_MIN_IMPRESSIONS = 100   # don't rank anything below this


@dataclass
class VariantStats:
    variant_id: str
    launch_id: str
    impressions: int
    clicks: int
    orders: int
    spend_usd: float
    revenue_usd: float
    ctr: float = 0.0
    cvr: float = 0.0
    cpa: float = 0.0
    roas: float = 0.0
    roas_lower_95: float = 0.0
    roas_upper_95: float = 0.0
    verdict: str = "insufficient_data"    # promote | prune | hold | insufficient_data
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "launch_id": self.launch_id,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "orders": self.orders,
            "spend_usd": round(self.spend_usd, 2),
            "revenue_usd": round(self.revenue_usd, 2),
            "ctr": round(self.ctr, 4),
            "cvr": round(self.cvr, 4),
            "cpa": round(self.cpa, 2),
            "roas": round(self.roas, 2),
            "roas_lower_95": round(self.roas_lower_95, 2),
            "roas_upper_95": round(self.roas_upper_95, 2),
            "verdict": self.verdict,
            "reason": self.reason,
        }


@dataclass
class OrchestrationReport:
    variants: list[VariantStats] = field(default_factory=list)
    promotes: list[VariantStats] = field(default_factory=list)
    prunes: list[VariantStats] = field(default_factory=list)
    refresh_slots: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variants": len(self.variants),
            "promotes": len(self.promotes),
            "prunes": len(self.prunes),
            "refresh_slots": self.refresh_slots,
            "top_promotes": [v.as_dict() for v in self.promotes[:5]],
        }


def orchestrate(stats: list[dict[str, Any]] | None = None) -> OrchestrationReport:
    """Run one orchestration pass.

    ``stats`` may be supplied directly (unit tests) or collected from
    memory when ``None``."""
    if stats is None:
        stats = _collect_stats()
    report = OrchestrationReport()
    if not stats:
        return report

    # Score every variant
    scored: list[VariantStats] = []
    for row in stats:
        variant = _score(row)
        scored.append(variant)
    report.variants = scored

    # Bucket by launch, pick winner per launch
    by_launch: dict[str, list[VariantStats]] = {}
    for v in scored:
        by_launch.setdefault(v.launch_id, []).append(v)

    for launch_id, group in by_launch.items():
        eligible = [v for v in group if v.impressions >= _MIN_IMPRESSIONS]
        if len(eligible) < 2:
            continue
        winner = max(eligible, key=lambda v: v.roas_lower_95)
        winner.verdict = "promote"
        winner.reason = (
            f"ROAS lower 95% bound {winner.roas_lower_95:.2f} leads "
            f"this launch's {len(eligible)} qualified variants"
        )
        report.promotes.append(winner)

        for v in eligible:
            if v is winner:
                continue
            if v.roas_upper_95 < winner.roas_lower_95:
                v.verdict = "prune"
                v.reason = (
                    f"upper bound {v.roas_upper_95:.2f} "
                    f"< winner lower bound {winner.roas_lower_95:.2f}"
                )
                report.prunes.append(v)
                report.refresh_slots.append({
                    "launch_id": launch_id,
                    "drop_variant": v.variant_id,
                    "replace_angle": _next_angle(group, v.variant_id),
                })
            else:
                v.verdict = "hold"
                v.reason = "credible-interval overlap — keep testing"

    return report


# ── Scoring + stats ────────────────────────────────────────────

def _score(row: dict[str, Any]) -> VariantStats:
    impressions = int(row.get("impressions") or 0)
    clicks = int(row.get("clicks") or 0)
    orders = int(row.get("orders") or 0)
    spend = float(row.get("spend_usd") or 0)
    revenue = float(row.get("revenue_usd") or 0)

    ctr = (clicks / impressions) if impressions else 0.0
    cvr = (orders / clicks) if clicks else 0.0
    cpa = (spend / orders) if orders else 0.0
    roas = (revenue / spend) if spend else 0.0

    # Bayesian bounds on ROAS. Observed ROAS = revenue / spend is the
    # point estimate; the uncertainty comes from the conversion-rate
    # posterior (Beta with prior α=1, β=1). When conversion_rate
    # uncertainty is high, so is ROAS uncertainty.
    if clicks > 0 and orders > 0 and spend > 0:
        a = orders + _PRIOR_A
        b = (clicks - orders) + _PRIOR_B
        p_mean = a / (a + b)
        p_var = (a * b) / (((a + b) ** 2) * (a + b + 1))
        p_stddev = math.sqrt(p_var)
        relative_stddev = p_stddev / p_mean if p_mean > 0 else 0.0
        mean = roas
        stddev = roas * relative_stddev
        lower = max(0.0, mean - _Z_95 * stddev)
        upper = mean + _Z_95 * stddev
    else:
        lower = upper = 0.0

    return VariantStats(
        variant_id=str(row.get("variant_id") or "?"),
        launch_id=str(row.get("launch_id") or "?"),
        impressions=impressions, clicks=clicks, orders=orders,
        spend_usd=spend, revenue_usd=revenue,
        ctr=ctr, cvr=cvr, cpa=cpa, roas=roas,
        roas_lower_95=lower, roas_upper_95=upper,
    )


def _next_angle(group: list[VariantStats], drop_id: str) -> str:
    """Suggest an angle the launch hasn't used yet — we include the
    dropped variant's angle in the "used" set because we don't want
    the replacement to run the same angle that just failed.
    """
    used = set()
    for v in group:
        # variant_id format is usually v1_hook / v2_benefits / v3_proof
        if "_" in v.variant_id:
            used.add(v.variant_id.split("_", 1)[1])
    for angle in ("hook", "benefits", "proof", "urgency", "comparison"):
        if angle not in used:
            return angle
    return "hook"


def _collect_stats() -> list[dict[str, Any]]:
    """Aggregate per-variant metrics from memory. Each launch's order
    events carry ``variant:<id>`` tags; ad_insight events carry
    impressions + spend. Join them by variant_id."""
    try:
        from core.memory.intelligence import get_memory_intelligence
    except Exception:
        return []
    mi = get_memory_intelligence()

    orders = mi.retrieve(category="order", min_score=0.0, limit=2000)
    insights = mi.retrieve(category="ad_insight", min_score=0.0, limit=2000)

    stats: dict[str, dict[str, Any]] = {}

    def _tags_of(row: dict[str, Any]) -> list[str]:
        import json
        tags = row.get("tags") or []
        if isinstance(tags, str):
            try:
                parsed = json.loads(tags)
                tags = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                tags = []
        return [t for t in tags if isinstance(t, str)]

    def _find_launch(tags: list[str]) -> str:
        for t in tags:
            if t.startswith("launch:"):
                return t.split(":", 1)[1]
        return ""

    def _find_variant(tags: list[str]) -> str:
        for t in tags:
            if t.startswith("variant:"):
                return t.split(":", 1)[1]
        return ""

    for row in orders:
        tags = _tags_of(row)
        launch = _find_launch(tags)
        variant = _find_variant(tags)
        if not launch or not variant:
            continue
        key = f"{launch}::{variant}"
        s = stats.setdefault(key, _blank(launch, variant))
        content = row.get("content") or {}
        total = float(content.get("total_price", 0) or 0)
        s["orders"] += 1
        s["revenue_usd"] += total

    for row in insights:
        tags = _tags_of(row)
        launch = _find_launch(tags)
        variant = _find_variant(tags)
        if not launch or not variant:
            continue
        key = f"{launch}::{variant}"
        s = stats.setdefault(key, _blank(launch, variant))
        content = row.get("content") or {}
        s["impressions"] += int(content.get("impressions", 0) or 0)
        s["clicks"] += int(content.get("clicks", 0) or 0)
        s["spend_usd"] += float(content.get("spend_usd", 0) or 0)

    return list(stats.values())


def _blank(launch: str, variant: str) -> dict[str, Any]:
    return {
        "launch_id": launch, "variant_id": variant,
        "impressions": 0, "clicks": 0, "orders": 0,
        "spend_usd": 0.0, "revenue_usd": 0.0,
    }
