"""Campaign Optimizer — auto-optimize ad campaigns based on performance metrics.

Rules:
  - ROAS < 2.0 for 24h → pause campaign
  - ROAS > 4.0 → increase budget 20%
  - CTR < 1% → flag for creative refresh
  - CPC > target → reduce bid
  - Winning campaigns → scale up
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.campaign")

# Thresholds
ROAS_PAUSE = 2.0
ROAS_BOOST = 4.0
CTR_MIN = 1.0
BUDGET_BOOST_PCT = 20
BUDGET_REDUCE_PCT = 15


class CampaignOptimizer:
    """Evaluates campaign metrics and produces optimization actions."""

    def optimize(self, campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze campaigns and return optimization actions.

        Each campaign dict should have: campaign_id, roas, ctr, cpc, budget, status
        """
        actions = []

        for camp in campaigns:
            if not isinstance(camp, dict):
                continue
            cid = camp.get("campaign_id", camp.get("id", "unknown"))
            roas = safe_float(camp.get("roas"))
            ctr = safe_float(camp.get("ctr"))
            cpc = safe_float(camp.get("cpc"))
            budget = safe_float(camp.get("budget"))
            status = camp.get("status", "active")
            spend = safe_float(camp.get("spend"))
            revenue = safe_float(camp.get("revenue"))

            # Skip paused campaigns
            if status == "paused":
                continue

            camp_actions = []

            # Rule 1: ROAS too low → pause
            if roas > 0 and roas < ROAS_PAUSE and spend > 10:
                camp_actions.append({
                    "action": "pause",
                    "campaign_id": cid,
                    "reason": f"ROAS {roas:.1f} below minimum {ROAS_PAUSE}",
                    "priority": "high",
                    "expected_savings": round(budget * 0.8, 2),
                })

            # Rule 2: ROAS high → increase budget
            elif roas >= ROAS_BOOST:
                boost = round(budget * BUDGET_BOOST_PCT / 100, 2)
                camp_actions.append({
                    "action": "increase_budget",
                    "campaign_id": cid,
                    "reason": f"ROAS {roas:.1f} exceeds target {ROAS_BOOST} — scaling up",
                    "priority": "medium",
                    "new_budget": round(budget + boost, 2),
                    "increase_amount": boost,
                })

            # Rule 3: CTR too low → creative refresh needed
            if ctr > 0 and ctr < CTR_MIN:
                camp_actions.append({
                    "action": "refresh_creative",
                    "campaign_id": cid,
                    "reason": f"CTR {ctr:.1f}% below minimum {CTR_MIN}%",
                    "priority": "medium",
                })

            # Rule 4: Moderate ROAS but declining → reduce budget
            if 2.0 <= roas < 3.0 and ctr < 2.0:
                reduce = round(budget * BUDGET_REDUCE_PCT / 100, 2)
                camp_actions.append({
                    "action": "reduce_budget",
                    "campaign_id": cid,
                    "reason": f"ROAS {roas:.1f} borderline, CTR {ctr:.1f}% low — reducing exposure",
                    "priority": "low",
                    "new_budget": round(budget - reduce, 2),
                    "reduce_amount": reduce,
                })

            if not camp_actions:
                camp_actions.append({
                    "action": "maintain",
                    "campaign_id": cid,
                    "reason": f"ROAS {roas:.1f}, CTR {ctr:.1f}% — performing within targets",
                    "priority": "none",
                })

            actions.extend(camp_actions)

        return actions

    def get_campaign_health(self, campaigns: list[dict[str, Any]]) -> dict[str, Any]:
        """Overall campaign portfolio health assessment."""
        if not campaigns:
            return {"status": "no_campaigns"}

        total_spend = sum(safe_float(c.get("spend")) for c in campaigns)
        total_revenue = sum(safe_float(c.get("revenue")) for c in campaigns)
        active = sum(1 for c in campaigns if c.get("status") != "paused")
        roas_values = [safe_float(c.get("roas")) for c in campaigns if safe_float(c.get("roas")) > 0]

        actions = self.optimize(campaigns)
        pause_count = sum(1 for a in actions if a.get("action") == "pause")
        boost_count = sum(1 for a in actions if a.get("action") == "increase_budget")

        avg_roas = round(sum(roas_values) / max(len(roas_values), 1), 2) if roas_values else 0
        grade = "A" if avg_roas > 4 else "B" if avg_roas > 2.5 else "C" if avg_roas > 1.5 else "F"

        return {
            "total_campaigns": len(campaigns),
            "active": active,
            "total_spend": round(total_spend, 2),
            "total_revenue": round(total_revenue, 2),
            "portfolio_roas": round(total_revenue / max(total_spend, 0.01), 2),
            "avg_roas": avg_roas,
            "grade": grade,
            "actions_needed": len([a for a in actions if a.get("action") != "maintain"]),
            "campaigns_to_pause": pause_count,
            "campaigns_to_boost": boost_count,
        }
