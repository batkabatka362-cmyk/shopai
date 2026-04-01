"""CausalGraph — links events into cause-effect chains.

"Revenue dropped 22%" is noise.
"Ad stopped 3 days ago (0.82) + competitor price cut (0.71) → revenue drop" is intelligence.

Uses known causal templates to detect chains in event streams.
Each chain has a strength score (0-1) based on temporal proximity,
correlation, and domain likelihood.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("causal.graph")


# Known causal chain templates
# Each template: list of (cause_event, effect_event, base_strength, max_days_apart)
CAUSAL_TEMPLATES = [
    # Marketing → Traffic → Revenue
    {"chain": ["ad_stop", "traffic_drop", "revenue_drop"], "base_strength": 0.85, "max_days": 7,
     "description": "Stopping ads causes traffic to drop, leading to revenue decline"},
    {"chain": ["ad_budget_cut", "traffic_drop", "revenue_drop"], "base_strength": 0.75, "max_days": 10,
     "description": "Reducing ad budget causes gradual traffic decline"},
    {"chain": ["creative_fatigue", "ctr_drop", "traffic_drop"], "base_strength": 0.70, "max_days": 14,
     "description": "Stale ad creatives lose CTR, reducing traffic"},

    # Competition → Conversion → Revenue
    {"chain": ["competitor_price_cut", "conversion_drop", "revenue_drop"], "base_strength": 0.80, "max_days": 7,
     "description": "Competitor lowering prices diverts customers"},
    {"chain": ["competitor_new_product", "traffic_shift", "revenue_drop"], "base_strength": 0.60, "max_days": 14,
     "description": "Competitor launches competing product"},

    # Inventory → Sales → Customer
    {"chain": ["stockout", "lost_sales", "customer_churn"], "base_strength": 0.90, "max_days": 14,
     "description": "Out-of-stock products cause lost sales and customer frustration"},
    {"chain": ["low_stock", "reduced_variants", "conversion_drop"], "base_strength": 0.65, "max_days": 7,
     "description": "Low stock reduces available options, hurting conversion"},

    # Pricing → Demand → Revenue
    {"chain": ["price_increase", "conversion_drop"], "base_strength": 0.75, "max_days": 3,
     "description": "Price increases reduce conversion on elastic products"},
    {"chain": ["price_decrease", "margin_drop"], "base_strength": 0.90, "max_days": 1,
     "description": "Price cuts immediately reduce margins"},

    # Customer Experience → Trust → Revenue
    {"chain": ["review_drop", "trust_decline", "conversion_drop"], "base_strength": 0.70, "max_days": 30,
     "description": "Declining reviews erode customer trust"},
    {"chain": ["shipping_delay", "complaints", "churn"], "base_strength": 0.80, "max_days": 14,
     "description": "Late deliveries cause complaints and customer loss"},
    {"chain": ["refund_spike", "review_drop", "trust_decline"], "base_strength": 0.65, "max_days": 21,
     "description": "Many refunds lead to negative reviews"},

    # System → Performance
    {"chain": ["api_error", "data_stale", "bad_decision"], "base_strength": 0.85, "max_days": 2,
     "description": "API failures cause stale data which leads to bad decisions"},
    {"chain": ["email_deliverability_drop", "engagement_drop", "churn"], "base_strength": 0.60, "max_days": 30,
     "description": "Poor email delivery reduces engagement"},
]

# Event type synonyms (normalize different names)
EVENT_SYNONYMS = {
    "revenue.drop": "revenue_drop",
    "revenue.increase": "revenue_increase",
    "product.price_change": "price_change",
    "product.out_of_stock": "stockout",
    "campaign.underperform": "creative_fatigue",
    "order.cancelled": "refund_spike",
    "ad_stopped": "ad_stop",
    "traffic_decreased": "traffic_drop",
    "conversion_decreased": "conversion_drop",
}


class CausalGraph:
    """Detects causal chains in event streams.

    Usage:
        graph = CausalGraph()
        result = graph.analyze(
            events=[
                {"type": "ad_stop", "timestamp": ..., "data": {}},
                {"type": "traffic_drop", "timestamp": ..., "data": {"change": -0.30}},
                {"type": "revenue_drop", "timestamp": ..., "data": {"change": -0.22}},
            ],
        )
        # Returns chains with strength scores
    """

    def analyze(
        self,
        events: list[dict[str, Any]],
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Analyze events for causal chains.

        Args:
            events: List of events with type, timestamp/days_ago, and data
            metrics: Optional current metrics (revenue_change, conversion_change, etc.)

        Returns:
            {"chains": [...], "root_causes": [...], "recommendations": [...]}
        """
        if not events:
            return {"chains": [], "root_causes": [], "recommendations": []}

        # Normalize events
        normalized = self._normalize_events(events)

        # Match against causal templates
        chains = []
        for template in CAUSAL_TEMPLATES:
            match = self._match_template(template, normalized)
            if match:
                chains.append(match)

        # Sort by strength
        chains.sort(key=lambda c: c["strength"], reverse=True)

        # Extract root causes (first event in each chain)
        root_causes = []
        seen_roots = set()
        for chain in chains:
            root = chain["events"][0]
            if root not in seen_roots:
                root_causes.append({
                    "event": root,
                    "strength": chain["strength"],
                    "leads_to": chain["events"][-1],
                    "chain": " → ".join(chain["events"]),
                })
                seen_roots.add(root)

        # Generate recommendations
        recommendations = self._generate_recommendations(chains)

        return {
            "chains": chains,
            "chain_count": len(chains),
            "root_causes": root_causes,
            "recommendations": recommendations,
        }

    def explain(self, events: list[dict[str, Any]], target_metric: str = "revenue_drop") -> str:
        """Generate a plain-language explanation for why a metric changed."""
        result = self.analyze(events)
        chains = [c for c in result["chains"] if target_metric in c["events"]]

        if not chains:
            return f"No causal chains found for {target_metric}. May be due to external factors not tracked."

        parts = [f"Analysis of {target_metric}:"]
        for i, chain in enumerate(chains[:3], 1):
            parts.append(
                f"  {i}. {chain['description']} "
                f"(strength: {chain['strength']:.0%}, "
                f"chain: {' → '.join(chain['events'])})"
            )

        if result["recommendations"]:
            parts.append("\nRecommended actions:")
            for rec in result["recommendations"][:3]:
                parts.append(f"  - {rec}")

        return "\n".join(parts)

    def _normalize_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize event types and compute days_ago."""
        now = time.time()
        normalized = []

        for event in events:
            if not isinstance(event, dict):
                continue

            event_type = event.get("type", event.get("event_type", ""))
            event_type = EVENT_SYNONYMS.get(event_type, event_type)

            ts = event.get("timestamp", 0)
            days_ago = event.get("days_ago", 0)
            if ts and not days_ago:
                days_ago = max(0, (now - ts) / 86400)

            normalized.append({
                "type": event_type,
                "days_ago": round(days_ago, 1),
                "data": event.get("data", {}),
            })

        return normalized

    def _match_template(self, template: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Try to match a causal template against observed events."""
        chain_events = template["chain"]
        max_days = template["max_days"]

        # Check if we have events matching the chain
        matched = []
        for chain_event in chain_events:
            found = None
            for event in events:
                if event["type"] == chain_event:
                    found = event
                    break
            if found:
                matched.append(found)

        # Need at least 2 events in the chain to count
        if len(matched) < 2:
            return None

        # Check temporal order and proximity
        for i in range(len(matched) - 1):
            day_diff = abs(matched[i]["days_ago"] - matched[i + 1]["days_ago"])
            if day_diff > max_days:
                return None

        # Calculate strength: base × temporal_proximity × coverage
        coverage = len(matched) / len(chain_events)
        avg_days = sum(m["days_ago"] for m in matched) / max(len(matched), 1)
        temporal_factor = max(0.3, 1.0 - avg_days / max(max_days * 2, 1))

        strength = round(
            template["base_strength"] * coverage * temporal_factor,
            3,
        )

        if strength < 0.3:
            return None

        return {
            "events": [m["type"] for m in matched],
            "full_chain": chain_events,
            "matched_count": len(matched),
            "total_in_chain": len(chain_events),
            "strength": strength,
            "description": template["description"],
            "temporal_span_days": round(max(m["days_ago"] for m in matched) - min(m["days_ago"] for m in matched), 1),
        }

    def _generate_recommendations(self, chains: list[dict[str, Any]]) -> list[str]:
        """Generate actionable recommendations from detected chains."""
        recommendations = []
        seen = set()

        action_map = {
            "ad_stop": "Restart ad campaigns immediately",
            "ad_budget_cut": "Restore ad budget to previous level",
            "creative_fatigue": "Rotate ad creatives — current ones are stale",
            "competitor_price_cut": "Review pricing strategy — competitor undercut you",
            "competitor_new_product": "Differentiate product positioning or adjust pricing",
            "stockout": "Emergency reorder — products out of stock",
            "low_stock": "Increase safety stock levels and reorder",
            "price_increase": "Consider rolling back recent price increase",
            "review_drop": "Launch review collection campaign (post-purchase emails)",
            "shipping_delay": "Switch to faster carrier or set realistic delivery expectations",
            "refund_spike": "Investigate product quality issues causing refunds",
            "api_error": "Check API connections and fix integration issues",
            "email_deliverability_drop": "Clean email list, check spam score, warm up sending domain",
        }

        for chain in chains:
            root = chain["events"][0]
            if root in action_map and root not in seen:
                recommendations.append(action_map[root])
                seen.add(root)

        return recommendations
