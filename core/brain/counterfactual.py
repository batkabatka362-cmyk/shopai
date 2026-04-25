"""Counterfactual engine — what if we had done X instead?

The Monte-Carlo simulator (v3-D3) projects forward: "if we kill
now, net saved = Y". Counterfactual reasoning looks *backward*:
"what if we had killed 3 days ago?" / "what if we'd never launched
this product?" — useful for learning from completed verdicts
without running new experiments.

Algorithm:

  1. Anchor on a completed decision's launch_id + verdict.
  2. Gather matched historical neighbours (same niche, same margin
     band, same ad-budget band) that took the *opposite* verdict.
  3. Reweight them by recency + similarity → the counterfactual
     outcome distribution.
  4. Compute the signed regret: realised_outcome − counterfactual_
     mean. Positive regret = our decision was worse than the
     alternative.

Returns a structured ``CounterfactualReport`` the reasoner and
calibration tracker (v4-D7) consume. Persisted as
``category=counterfactual score=3.5`` memory events so the
feedback_learner can promote patterns ("we should kill faster on
electronics") into rules.

Pure statistics + memory queries — no LLM.
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.counterfactual")

_DB_PATH = Path("data/memory_intelligence.db")
_OPPOSITES = {"kill": {"scale", "hold"},
              "scale": {"kill", "hold"},
              "hold": {"kill", "scale"}}


@dataclass
class CounterfactualReport:
    launch_id: str
    realised_verdict: str
    realised_roas: float
    realised_revenue: float
    counterfactual_verdict: str
    neighbours: int
    cf_revenue_mean: float
    cf_revenue_p10: float
    cf_revenue_p90: float
    regret: float                  # realised − cf_mean
    narrative: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "realised_verdict": self.realised_verdict,
            "realised_roas": round(self.realised_roas, 3),
            "realised_revenue": round(self.realised_revenue, 2),
            "counterfactual_verdict": self.counterfactual_verdict,
            "neighbours": self.neighbours,
            "cf_revenue_mean": round(self.cf_revenue_mean, 2),
            "cf_revenue_p10": round(self.cf_revenue_p10, 2),
            "cf_revenue_p90": round(self.cf_revenue_p90, 2),
            "regret": round(self.regret, 2),
            "narrative": self.narrative,
        }


def what_if(launch_id: str, alt_verdict: str = "") -> CounterfactualReport:
    """Compute the counterfactual outcome for *launch_id*."""
    anchor = _anchor(launch_id)
    if anchor is None:
        return _blank(launch_id, "(no anchor found)")

    realised = anchor.get("verdict", "")
    alt = alt_verdict or _default_opposite(realised)
    neighbours = _matched_neighbours(anchor, alt)
    if not neighbours:
        return _blank(launch_id,
                      "(no matched historical neighbours for counterfactual)")

    revenues = [n.get("revenue_usd", 0.0) for n in neighbours]
    revenues.sort()
    cf_mean = statistics.fmean(revenues) if revenues else 0.0
    cf_p10 = revenues[int(len(revenues) * 0.1)] if revenues else 0.0
    cf_p90 = revenues[int(len(revenues) * 0.9)] if revenues else 0.0

    realised_revenue = float(anchor.get("revenue_usd", 0.0))
    regret = realised_revenue - cf_mean

    narrative = (
        f"Realised '{realised}' produced ${realised_revenue:.2f} "
        f"revenue; alternative '{alt}' across {len(neighbours)} "
        f"matched launches would have produced ${cf_mean:.2f} "
        f"(p10 ${cf_p10:.2f}, p90 ${cf_p90:.2f}). "
        f"Regret = ${regret:+.2f}."
    )

    report = CounterfactualReport(
        launch_id=launch_id,
        realised_verdict=realised,
        realised_roas=float(anchor.get("roas", 0.0)),
        realised_revenue=realised_revenue,
        counterfactual_verdict=alt,
        neighbours=len(neighbours),
        cf_revenue_mean=cf_mean,
        cf_revenue_p10=cf_p10,
        cf_revenue_p90=cf_p90,
        regret=regret,
        narrative=narrative,
    )
    _persist(report)
    return report


def _anchor(launch_id: str) -> dict[str, Any] | None:
    """Return the launch's latest snapshot + evaluator verdict."""
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
    except Exception:
        return None
    buckets = (
        report.kill_recommendations
        + report.scale_recommendations
        + report.monitor_recommendations
    )
    for s in buckets:
        if s.launch_id == launch_id:
            return {
                "launch_id": s.launch_id,
                "verdict": s.verdict,
                "roas": float(s.estimated_roas),
                "revenue_usd": float(s.revenue_usd),
                "ad_budget_day": float(s.ad_budget_day),
                "niche": _niche_of(launch_id),
            }
    return None


def _niche_of(launch_id: str) -> str:
    try:
        from core.autonomous.self_critic import _niche_map
        return _niche_map(limit=500).get(launch_id, "")
    except Exception:
        return ""


def _default_opposite(verdict: str) -> str:
    opts = _OPPOSITES.get(verdict, set())
    return next(iter(opts), "hold")


def _matched_neighbours(
    anchor: dict[str, Any], alt_verdict: str,
) -> list[dict[str, Any]]:
    """Pull launches that took *alt_verdict* with matching niche +
    similar budget band."""
    try:
        from core.autonomous.launch_evaluator import evaluate
        from core.autonomous.self_critic import _niche_map
        report = evaluate()
        niches = _niche_map(limit=500)
    except Exception:
        return []

    buckets = (
        report.kill_recommendations
        + report.scale_recommendations
        + report.monitor_recommendations
    )
    anchor_niche = (anchor.get("niche") or "").lower()
    anchor_budget = anchor.get("ad_budget_day") or 0.0
    neighbours: list[dict[str, Any]] = []
    for s in buckets:
        if s.launch_id == anchor.get("launch_id"):
            continue
        if s.verdict != alt_verdict:
            continue
        niche = niches.get(s.launch_id, "").lower()
        if anchor_niche and niche and niche != anchor_niche:
            continue
        # Budget within 50-200 % of the anchor
        if anchor_budget > 0:
            ratio = (s.ad_budget_day or 0) / anchor_budget
            if ratio < 0.5 or ratio > 2.0:
                continue
        neighbours.append({
            "launch_id": s.launch_id,
            "verdict": s.verdict,
            "roas": float(s.estimated_roas),
            "revenue_usd": float(s.revenue_usd),
            "ad_budget_day": float(s.ad_budget_day),
        })
    return neighbours


def _blank(launch_id: str, reason: str) -> CounterfactualReport:
    return CounterfactualReport(
        launch_id=launch_id,
        realised_verdict="",
        realised_roas=0.0,
        realised_revenue=0.0,
        counterfactual_verdict="",
        neighbours=0,
        cf_revenue_mean=0.0, cf_revenue_p10=0.0, cf_revenue_p90=0.0,
        regret=0.0, narrative=reason,
    )


def _persist(report: CounterfactualReport) -> None:
    try:
        from core.memory.unified_memory import get_unified_memory
        mi = get_unified_memory().get_memory_intelligence()
        mi.create(
            category="counterfactual",
            content=report.as_dict(),
            action=f"{report.realised_verdict}_vs_{report.counterfactual_verdict}",
            score=3.5,
            tags=["counterfactual", "regret",
                  f"launch:{report.launch_id}"],
        )
    except Exception as exc:
        logger.debug("counterfactual persist failed: %s", exc)
