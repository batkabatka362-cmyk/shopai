"""CompoundingOptimizer — small improvements compound into big results.

5% conversion + 5% AOV + 5% traffic = 16% revenue (NOT 15%).
This module tracks compound effects, identifies flywheels, and
prioritizes improvements by their COMPOUND impact, not individual.

Revenue = Traffic × Conversion × AOV
If each improves 10%: 1.10 × 1.10 × 1.10 = 1.331 = +33.1% (not +30%)
"""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.compounding")

# Known flywheels (self-reinforcing loops)
FLYWHEELS = {
    "review_flywheel": {
        "loop": ["good_product → positive_review → trust_increase → more_sales → more_reviews"],
        "friction_points": ["low_review_request_rate", "poor_product_quality", "no_photo_incentive"],
        "boost_actions": ["post_purchase_review_email", "photo_review_incentive", "display_reviews_prominently"],
        "multiplier": 1.15,  # 15% compounding effect per quarter
    },
    "content_flywheel": {
        "loop": ["quality_content → organic_traffic → sales → revenue_for_content → more_content"],
        "friction_points": ["no_content_strategy", "inconsistent_publishing", "poor_seo"],
        "boost_actions": ["weekly_blog_posts", "seo_optimization", "content_repurposing"],
        "multiplier": 1.10,
    },
    "customer_loyalty_flywheel": {
        "loop": ["good_experience → repeat_purchase → higher_LTV → more_budget → better_experience"],
        "friction_points": ["poor_post_purchase", "no_loyalty_program", "slow_shipping"],
        "boost_actions": ["loyalty_program", "surprise_delight", "personalized_recommendations"],
        "multiplier": 1.20,
    },
    "data_flywheel": {
        "loop": ["more_customers → more_data → better_decisions → higher_conversion → more_customers"],
        "friction_points": ["small_sample_size", "no_analytics", "not_using_data"],
        "boost_actions": ["implement_analytics", "a_b_testing", "personalization"],
        "multiplier": 1.08,
    },
    "referral_flywheel": {
        "loop": ["happy_customer → referral → new_customer → happy_customer → more_referrals"],
        "friction_points": ["no_referral_program", "low_nps", "no_incentive"],
        "boost_actions": ["launch_referral_program", "improve_nps", "referral_incentives"],
        "multiplier": 1.25,
    },
}


class CompoundingOptimizer:
    """Analyzes compound effects and prioritizes by compound impact.

    Usage:
        optimizer = CompoundingOptimizer()
        result = optimizer.analyze_compound_impact(improvements)
        flywheels = optimizer.detect_flywheels(store_data)
    """

    def analyze_compound_impact(
        self,
        improvements: list[dict[str, Any]],
        current_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Calculate compound impact of multiple simultaneous improvements.

        Args:
            improvements: [{"name": "...", "metric": "traffic|conversion|aov", "lift_pct": 5}, ...]
            current_metrics: {"traffic": 10000, "conversion": 0.02, "aov": 50}
        """
        metrics = current_metrics or {"traffic": 10000, "conversion_rate": 0.02, "aov": 50}
        traffic = safe_float(metrics.get("traffic", 10000))
        cvr = safe_float(metrics.get("conversion_rate", 0.02))
        aov = safe_float(metrics.get("aov", 50))

        current_revenue = traffic * cvr * aov

        # Calculate individual vs compound
        traffic_mult = 1.0
        cvr_mult = 1.0
        aov_mult = 1.0
        linear_sum = 0

        for imp in improvements:
            lift = safe_float(imp.get("lift_pct", 0)) / 100
            metric = imp.get("metric", "")
            linear_sum += lift

            if metric == "traffic":
                traffic_mult *= (1 + lift)
            elif metric in ("conversion", "conversion_rate"):
                cvr_mult *= (1 + lift)
            elif metric == "aov":
                aov_mult *= (1 + lift)

        compound_multiplier = traffic_mult * cvr_mult * aov_mult
        compound_revenue = traffic * traffic_mult * cvr * cvr_mult * aov * aov_mult
        linear_revenue = current_revenue * (1 + linear_sum)

        compound_lift = (compound_multiplier - 1) * 100
        linear_lift = linear_sum * 100
        bonus = compound_lift - linear_lift

        return {
            "current_revenue": round(current_revenue, 2),
            "improvements": improvements,
            "linear_lift_pct": round(linear_lift, 1),
            "compound_lift_pct": round(compound_lift, 1),
            "compound_bonus_pct": round(bonus, 1),
            "projected_revenue": round(compound_revenue, 2),
            "revenue_gain": round(compound_revenue - current_revenue, 2),
            "multipliers": {
                "traffic": round(traffic_mult, 4),
                "conversion": round(cvr_mult, 4),
                "aov": round(aov_mult, 4),
                "compound": round(compound_multiplier, 4),
            },
            "insight": (
                f"{len(improvements)} improvements compound to +{compound_lift:.1f}% revenue "
                f"(not +{linear_lift:.1f}% linear). "
                f"Compound bonus: +{bonus:.1f}% extra revenue."
            ),
        }

    def prioritize_by_compound(
        self,
        opportunities: list[dict[str, Any]],
        current_metrics: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Rank opportunities by their compound impact (not just individual lift)."""
        if not opportunities:
            return []

        # Calculate marginal compound impact of each
        ranked = []
        for opp in opportunities:
            # What's the revenue impact if ONLY this improvement is made?
            individual = self.analyze_compound_impact([opp], current_metrics)

            # What's the compound bonus when combined with ALL others?
            others = [o for o in opportunities if o != opp]
            without = self.analyze_compound_impact(others, current_metrics) if others else {"projected_revenue": current_metrics.get("revenue", 0) if current_metrics else 0}
            with_all = self.analyze_compound_impact(opportunities, current_metrics)

            marginal_impact = with_all["projected_revenue"] - without.get("projected_revenue", 0)

            ranked.append({
                **opp,
                "individual_lift_pct": round((individual["compound_lift_pct"]), 1),
                "marginal_compound_revenue": round(marginal_impact, 2),
                "compound_priority": round(marginal_impact, 2),
            })

        ranked.sort(key=lambda r: r["compound_priority"], reverse=True)
        return ranked

    def detect_flywheels(self, store_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Detect which flywheels are active, stalled, or potential."""
        results = []

        for name, config in FLYWHEELS.items():
            status = "potential"
            friction = config["friction_points"]
            active_frictions = []

            # Check if flywheel is active based on store data
            if store_data:
                if name == "review_flywheel":
                    reviews = store_data.get("avg_reviews_per_product", 0)
                    status = "active" if reviews > 5 else "stalled" if reviews > 0 else "potential"
                    if reviews < 3:
                        active_frictions.append("low_review_count")

                elif name == "customer_loyalty_flywheel":
                    repeat_rate = store_data.get("repeat_purchase_rate", 0)
                    status = "active" if repeat_rate > 30 else "stalled" if repeat_rate > 10 else "potential"
                    if repeat_rate < 20:
                        active_frictions.append("low_repeat_rate")

                elif name == "referral_flywheel":
                    has_referral = store_data.get("has_referral_program", False)
                    status = "active" if has_referral else "potential"

            results.append({
                "flywheel": name,
                "loop": config["loop"],
                "status": status,
                "quarterly_multiplier": f"{config['multiplier']}x",
                "annual_multiplier": f"{config['multiplier'] ** 4:.2f}x",
                "friction_points": friction,
                "active_frictions": active_frictions,
                "boost_actions": config["boost_actions"],
            })

        active = [r for r in results if r["status"] == "active"]
        stalled = [r for r in results if r["status"] == "stalled"]

        return {
            "flywheels": results,
            "active_count": len(active),
            "stalled_count": len(stalled),
            "top_opportunity": next(
                (r for r in results if r["status"] in ("stalled", "potential")),
                None,
            ),
            "insight": (
                f"{len(active)} flywheels active, {len(stalled)} stalled. "
                f"Fix stalled flywheels for highest compound growth."
            ),
        }

    def project_growth(
        self,
        current_monthly_revenue: float,
        monthly_improvement_pct: float = 5,
        months: int = 12,
    ) -> dict[str, Any]:
        """Project compound growth over time."""
        projections = []
        revenue = current_monthly_revenue
        total = 0

        for month in range(1, months + 1):
            revenue *= (1 + monthly_improvement_pct / 100)
            total += revenue
            projections.append({
                "month": month,
                "revenue": round(revenue, 2),
                "cumulative": round(total, 2),
                "growth_from_start": round((revenue / current_monthly_revenue - 1) * 100, 1),
            })

        linear_total = current_monthly_revenue * months * (1 + monthly_improvement_pct / 100 * months / 2)

        return {
            "start_revenue": current_monthly_revenue,
            "monthly_improvement": f"{monthly_improvement_pct}%",
            "months": months,
            "final_monthly": round(revenue, 2),
            "total_compound": round(total, 2),
            "total_linear": round(linear_total, 2),
            "compound_advantage": round(total - linear_total, 2),
            "final_growth": f"+{(revenue / current_monthly_revenue - 1) * 100:.0f}%",
            "projections": projections,
            "insight": (
                f"{monthly_improvement_pct}% monthly improvement compounds to "
                f"+{(revenue / current_monthly_revenue - 1) * 100:.0f}% after {months} months "
                f"(not +{monthly_improvement_pct * months}% linear)"
            ),
        }
