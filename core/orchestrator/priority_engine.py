"""PriorityEngine — decides what the store needs RIGHT NOW.

Instead of "run everything every time" (like FullSystemLoop),
the PriorityEngine examines the StoreSnapshot and ranks domains
by urgency:

  - Stockout = critical → focus on inventory
  - Revenue drop = critical → focus on pricing/marketing
  - Churn spike = high → focus on retention
  - Everything OK = normal → focus on growth

Uses StrategyOptimizer weights + rule-based urgency + financial constraints.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("orchestrator.priority")


# Domain urgency rules — each rule examines the snapshot and returns urgency + reason
URGENCY_RULES = {
    "inventory": {
        "critical": lambda s: s.get("inventory", {}).get("out_of_stock_count", 0) > 0,
        "high": lambda s: s.get("inventory", {}).get("low_stock_pct", 0) > 30,
        "medium": lambda s: s.get("inventory", {}).get("low_stock_pct", 0) > 15,
    },
    "financial": {
        "critical": lambda s: s.get("financial", {}).get("critical_alerts", 0) > 0,
        "high": lambda s: s.get("financial", {}).get("health_grade") in ("D", "F"),
        "medium": lambda s: s.get("financial", {}).get("health_grade") == "C",
    },
    "customers": {
        "critical": lambda s: s.get("customers", {}).get("churn_risk_pct", 0) > 70,
        "high": lambda s: s.get("customers", {}).get("churn_risk_pct", 0) > 50,
        "medium": lambda s: s.get("customers", {}).get("churn_risk_pct", 0) > 30,
    },
    "marketing": {
        "high": lambda s: len(s.get("events", [])) > 3,
        "medium": lambda s: s.get("marketing", {}).get("optimization_actions", 0) > 2,
    },
    "system_health": {
        "high": lambda s: s.get("health", {}).get("overall_grade") in ("D", "F"),
        "medium": lambda s: s.get("health", {}).get("overall_grade") == "C",
    },
}

# Urgency level to numeric score
URGENCY_SCORES = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
    "normal": 10,
}

# Goal-domain affinity — which goals boost which domains
GOAL_DOMAIN_BOOST = {
    "maximize_profit": {"financial": 1.3, "inventory": 1.1, "marketing": 1.0},
    "grow_customers": {"customers": 1.3, "marketing": 1.2, "financial": 0.9},
    "increase_aov": {"marketing": 1.2, "financial": 1.1, "customers": 1.0},
}


class PriorityEngine:
    """Examines store snapshot and returns ranked priorities.

    Usage:
        engine = PriorityEngine()
        priorities = engine.compute(snapshot.get_situation(), goal="maximize_profit")
        # Returns: [{"domain": "inventory", "urgency": "critical", "score": 100, ...}, ...]
    """

    def compute(
        self,
        situation: dict[str, Any],
        goal: str = "maximize_profit",
        strategy_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Compute ranked priorities from the current store situation.

        Args:
            situation: Output from StoreSnapshot.get_situation()
            goal: Current business goal
            strategy_weights: Optional weights from StrategyOptimizer

        Returns:
            List of priorities sorted by score (highest first), each with:
            - domain: which area needs attention
            - urgency: critical/high/medium/low/normal
            - score: 0-100 priority score
            - reason: why this is prioritized
            - recommended_actions: what to do
        """
        priorities = []

        for domain, rules in URGENCY_RULES.items():
            urgency = "normal"
            reason = "No issues detected"

            # Check rules from most to least severe
            for level in ("critical", "high", "medium"):
                check_fn = rules.get(level)
                if check_fn and check_fn(situation):
                    urgency = level
                    reason = self._get_reason(domain, level, situation)
                    break

            # Compute score: base urgency + goal boost + strategy weight
            base_score = URGENCY_SCORES.get(urgency, 10)
            goal_boost = GOAL_DOMAIN_BOOST.get(goal, {}).get(domain, 1.0)
            strategy_boost = 1.0
            if strategy_weights:
                # Map domain to strategy weight keys
                domain_to_weight = {
                    "inventory": "product_launch",
                    "financial": "pricing_optimization",
                    "customers": "customer_retention",
                    "marketing": "aov_increase",
                }
                weight_key = domain_to_weight.get(domain)
                if weight_key and weight_key in strategy_weights:
                    strategy_boost = strategy_weights[weight_key]

            final_score = round(min(100, base_score * goal_boost * strategy_boost), 1)

            priorities.append({
                "domain": domain,
                "urgency": urgency,
                "score": final_score,
                "reason": reason,
                "recommended_actions": self._get_actions(domain, urgency, situation),
            })

        # Sort by score descending
        priorities.sort(key=lambda p: p["score"], reverse=True)

        logger.info(
            "Priorities computed: %s",
            ", ".join(f"{p['domain']}={p['urgency']}({p['score']})" for p in priorities),
        )
        return priorities

    def get_focus_domains(
        self,
        situation: dict[str, Any],
        goal: str = "maximize_profit",
        max_domains: int = 3,
    ) -> list[str]:
        """Get the top N domains to focus on this cycle."""
        priorities = self.compute(situation, goal)
        return [p["domain"] for p in priorities[:max_domains]]

    def has_critical(self, situation: dict[str, Any]) -> bool:
        """Check if any domain has critical urgency (needs immediate action)."""
        for domain, rules in URGENCY_RULES.items():
            check = rules.get("critical")
            if check and check(situation):
                return True
        return False

    def _get_reason(self, domain: str, urgency: str, situation: dict[str, Any]) -> str:
        """Generate human-readable reason for the priority."""
        if domain == "inventory":
            inv = situation.get("inventory", {})
            if urgency == "critical":
                return f"{inv.get('out_of_stock_count', 0)} products out of stock — sales being lost"
            if urgency == "high":
                return f"{inv.get('low_stock_pct', 0)}% of products at low stock — reorder needed"
            return f"{inv.get('low_stock_count', 0)} products below threshold"

        if domain == "financial":
            fin = situation.get("financial", {})
            if urgency == "critical":
                return f"{fin.get('critical_alerts', 0)} products selling below cost"
            if urgency == "high":
                return f"Financial health grade {fin.get('health_grade', '?')} — margins under pressure"
            return "Financial metrics need improvement"

        if domain == "customers":
            cust = situation.get("customers", {})
            return f"{cust.get('churn_risk_pct', 0)}% customers inactive — {urgency} churn risk"

        if domain == "marketing":
            mkt = situation.get("marketing", {})
            actions = mkt.get("optimization_actions", 0)
            return f"{actions} campaign optimization actions pending"

        if domain == "system_health":
            grade = situation.get("health", {}).get("overall_grade", "?")
            return f"System health grade: {grade}"

        return f"{domain}: {urgency} priority"

    def _get_actions(self, domain: str, urgency: str, situation: dict[str, Any]) -> list[str]:
        """Suggest actions for the domain based on urgency."""
        actions_map = {
            "inventory": {
                "critical": ["disable_out_of_stock_listings", "emergency_reorder", "reduce_ads_for_oos"],
                "high": ["reorder_low_stock", "adjust_safety_stock_levels"],
                "medium": ["review_inventory_levels"],
            },
            "financial": {
                "critical": ["raise_prices_below_cost", "pause_unprofitable_campaigns"],
                "high": ["review_pricing_strategy", "reduce_unnecessary_costs"],
                "medium": ["optimize_margins"],
            },
            "customers": {
                "critical": ["launch_emergency_retention", "send_winback_emails"],
                "high": ["segment_at_risk_customers", "create_retention_offers"],
                "medium": ["review_customer_engagement"],
            },
            "marketing": {
                "high": ["pause_underperforming_campaigns", "reallocate_budget"],
                "medium": ["optimize_ad_creatives", "test_new_audiences"],
            },
            "system_health": {
                "high": ["run_diagnostics", "check_api_connections"],
                "medium": ["review_system_metrics"],
            },
        }
        return actions_map.get(domain, {}).get(urgency, ["monitor"])
