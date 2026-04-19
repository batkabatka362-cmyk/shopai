"""Launch outcome evaluator.

Closes the last mile of the reward loop:

    Launch monitor recorded:   memory.create(category="launch")
    Order webhook recorded:    memory.create(category="order",
                                             tags=["launch:<id>"])
    ↓ (this module) ↓
    Per-launch KPIs            { revenue, order_count, aov, days_live }
    Kill/scale decisions       goal.ad_kill_roas / scale_roas thresholds

Determinism-first per CLAUDE.md §4b.A — no LLM here, just SQL-style
aggregation over the memory store. LLM is only called *later*, if the
owner wants a narrative for why a kill happened.

The daemon calls ``evaluate()`` once per cycle; the result is emitted
as advisory actions (no direct Meta Ads write yet — that lands when the
ads_launch adapter has live credentials).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("autonomous.launch_evaluator")


_SECONDS_PER_DAY = 86_400.0


@dataclass
class LaunchStats:
    launch_id: str
    registered_at: float
    shopify_product_id: int | None = None
    kill_roas: float = 1.5
    scale_roas: float = 2.0
    kill_after_days: int = 3
    ad_budget_day: float = 0.0

    # Populated from order events
    revenue_usd: float = 0.0
    order_count: int = 0
    last_order_at: float = 0.0

    # Derived
    days_live: float = 0.0
    aov: float = 0.0
    estimated_spend: float = 0.0
    estimated_roas: float = 0.0
    verdict: str = "insufficient_data"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "shopify_product_id": self.shopify_product_id,
            "revenue_usd": round(self.revenue_usd, 2),
            "order_count": self.order_count,
            "days_live": round(self.days_live, 2),
            "aov": round(self.aov, 2),
            "estimated_spend": round(self.estimated_spend, 2),
            "estimated_roas": round(self.estimated_roas, 2),
            "verdict": self.verdict,
            "reason": self.reason,
            "kill_roas": self.kill_roas,
            "scale_roas": self.scale_roas,
        }


@dataclass
class EvaluationReport:
    launches_tracked: int = 0
    launches_evaluated: int = 0
    kill_recommendations: list[LaunchStats] = field(default_factory=list)
    scale_recommendations: list[LaunchStats] = field(default_factory=list)
    monitor_recommendations: list[LaunchStats] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "launches_tracked": self.launches_tracked,
            "launches_evaluated": self.launches_evaluated,
            "kills": [s.as_dict() for s in self.kill_recommendations],
            "scales": [s.as_dict() for s in self.scale_recommendations],
            "monitors": [s.as_dict() for s in self.monitor_recommendations],
        }


def evaluate() -> EvaluationReport:
    """Compute per-launch KPIs + emit kill/scale/monitor buckets.

    Never raises — a memory-layer failure returns an empty report so
    the daemon's cycle doesn't abort on reward evaluation.
    """
    try:
        stats = _collect_launches()
        if not stats:
            return EvaluationReport()
        _attach_orders(stats)
        report = _bucket(stats)
        logger.info(
            "launch_evaluator: %d tracked, %d evaluated, %d kill / %d scale / %d monitor",
            report.launches_tracked,
            report.launches_evaluated,
            len(report.kill_recommendations),
            len(report.scale_recommendations),
            len(report.monitor_recommendations),
        )
        return report
    except Exception as exc:  # noqa: BLE001
        logger.warning("launch_evaluator failed: %s", exc)
        return EvaluationReport()


def _collect_launches() -> dict[str, LaunchStats]:
    """Pull every ``category='launch'`` memory event."""
    from core.memory.intelligence import get_memory_intelligence
    mi = get_memory_intelligence()
    rows = mi.retrieve(category="launch", min_score=0.0, limit=200)
    out: dict[str, LaunchStats] = {}
    for row in rows:
        content = row.get("content") or {}
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                content = {}
        lid = content.get("launch_id") or ""
        if not lid:
            continue
        kill_rule = content.get("kill_rule") or {}
        out[lid] = LaunchStats(
            launch_id=lid,
            registered_at=float(content.get("registered_at") or row.get("timestamp") or 0),
            shopify_product_id=content.get("shopify_product_id"),
            kill_roas=float(kill_rule.get("kill_roas", 1.5)),
            scale_roas=float(kill_rule.get("scale_roas", 2.0)),
            kill_after_days=int(kill_rule.get("after_days", 3)),
            ad_budget_day=float(kill_rule.get("ad_budget_day", 0.0)),
        )
    return out


def _attach_orders(stats: dict[str, LaunchStats]) -> None:
    """Aggregate orders by their ``launch:<id>`` tag."""
    from core.memory.intelligence import get_memory_intelligence
    mi = get_memory_intelligence()
    rows = mi.retrieve(category="order", min_score=0.0, limit=2000)
    now = time.time()
    for row in rows:
        tags = row.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        content = row.get("content") or {}
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                content = {}
        total = float(content.get("total_price", 0) or content.get("total", 0) or 0)
        ts = float(row.get("timestamp") or 0)
        for tag in tags:
            if not isinstance(tag, str) or not tag.startswith("launch:"):
                continue
            lid = tag[len("launch:"):]
            s = stats.get(lid)
            if not s:
                continue
            s.revenue_usd += total
            s.order_count += 1
            if ts > s.last_order_at:
                s.last_order_at = ts

    for s in stats.values():
        if s.registered_at:
            s.days_live = max(0.0, (now - s.registered_at) / _SECONDS_PER_DAY)
        if s.order_count:
            s.aov = s.revenue_usd / s.order_count
        if s.ad_budget_day and s.days_live > 0:
            s.estimated_spend = s.ad_budget_day * s.days_live
            if s.estimated_spend > 0:
                s.estimated_roas = s.revenue_usd / s.estimated_spend


def _bucket(stats: dict[str, LaunchStats]) -> EvaluationReport:
    """Classify launches into kill / scale / monitor buckets."""
    report = EvaluationReport(launches_tracked=len(stats))
    for s in stats.values():
        # Below minimum data horizon — wait, don't decide yet
        if s.days_live < s.kill_after_days:
            s.verdict = "waiting_for_data"
            s.reason = (
                f"{s.days_live:.1f} / {s.kill_after_days} days live "
                f"(orders so far: {s.order_count})"
            )
            report.monitor_recommendations.append(s)
            continue

        report.launches_evaluated += 1

        # No ad spend configured — we can't compute ROAS; just monitor
        if s.ad_budget_day <= 0:
            s.verdict = "monitor"
            s.reason = "no ad_budget_day set — launch tracked but ROAS undefined"
            report.monitor_recommendations.append(s)
            continue

        if s.estimated_roas < s.kill_roas:
            s.verdict = "kill"
            s.reason = (
                f"ROAS {s.estimated_roas:.2f} < kill threshold {s.kill_roas} "
                f"after {s.days_live:.1f} days (spend ${s.estimated_spend:.2f}, "
                f"revenue ${s.revenue_usd:.2f})"
            )
            report.kill_recommendations.append(s)
        elif s.estimated_roas >= s.scale_roas:
            s.verdict = "scale"
            s.reason = (
                f"ROAS {s.estimated_roas:.2f} ≥ scale threshold {s.scale_roas} "
                f"— double daily budget"
            )
            report.scale_recommendations.append(s)
        else:
            s.verdict = "hold"
            s.reason = (
                f"ROAS {s.estimated_roas:.2f} in safe zone "
                f"[{s.kill_roas}..{s.scale_roas}] — keep running"
            )
            report.monitor_recommendations.append(s)
    return report
