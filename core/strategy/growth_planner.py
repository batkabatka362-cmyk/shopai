"""GrowthPlanner — 3/6/12 month growth roadmaps.

System өдөр тутмын decision хийдэг, гэхдээ "3 сарын дараа хаашаа хүрэх вэ"
гэдгийг мэдэхгүй. GrowthPlanner backtrack тооцоолол хийнэ:

Revenue target → monthly milestones → required metrics → actions needed.
"""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("strategy.growth_planner")

# Growth levers and their typical impact ranges
GROWTH_LEVERS = {
    "traffic_increase": {
        "tactics": ["paid_ads_scaling", "seo_optimization", "influencer_partnerships", "content_marketing"],
        "typical_lift": (0.10, 0.40),  # 10-40% traffic increase
        "effort": "high",
        "time_to_impact": "1-3 months",
    },
    "conversion_optimization": {
        "tactics": ["landing_page_optimization", "checkout_simplification", "social_proof", "trust_badges"],
        "typical_lift": (0.10, 0.30),
        "effort": "medium",
        "time_to_impact": "2-4 weeks",
    },
    "aov_increase": {
        "tactics": ["upsell_crosssell", "bundle_offers", "free_shipping_threshold", "tiered_pricing"],
        "typical_lift": (0.10, 0.25),
        "effort": "low",
        "time_to_impact": "1-2 weeks",
    },
    "retention_improvement": {
        "tactics": ["email_automation", "loyalty_program", "subscription_model", "post_purchase_experience"],
        "typical_lift": (0.15, 0.40),
        "effort": "medium",
        "time_to_impact": "1-3 months",
    },
    "new_channel": {
        "tactics": ["tiktok_ads", "pinterest", "sms_marketing", "affiliate_program"],
        "typical_lift": (0.10, 0.30),
        "effort": "high",
        "time_to_impact": "2-4 months",
    },
    "product_expansion": {
        "tactics": ["new_product_line", "complementary_products", "private_label", "dropship_additions"],
        "typical_lift": (0.15, 0.50),
        "effort": "very_high",
        "time_to_impact": "3-6 months",
    },
}

# Budget allocation templates by stage
BUDGET_TEMPLATES = {
    "early_stage": {
        "description": "$0-$10K/month revenue",
        "paid_ads": 0.30,
        "content_seo": 0.15,
        "email_sms": 0.10,
        "tools_apps": 0.15,
        "product_dev": 0.20,
        "reserve": 0.10,
    },
    "growth_stage": {
        "description": "$10K-$50K/month revenue",
        "paid_ads": 0.35,
        "content_seo": 0.15,
        "email_sms": 0.10,
        "influencer": 0.10,
        "tools_apps": 0.10,
        "product_dev": 0.10,
        "reserve": 0.10,
    },
    "scale_stage": {
        "description": "$50K-$200K/month revenue",
        "paid_ads": 0.30,
        "content_seo": 0.10,
        "email_sms": 0.10,
        "influencer": 0.10,
        "new_channels": 0.10,
        "tools_apps": 0.10,
        "team": 0.10,
        "reserve": 0.10,
    },
    "enterprise_stage": {
        "description": "$200K+/month revenue",
        "paid_ads": 0.25,
        "content_seo": 0.10,
        "email_sms": 0.08,
        "influencer": 0.07,
        "new_channels": 0.10,
        "brand_building": 0.10,
        "team": 0.15,
        "international": 0.05,
        "reserve": 0.10,
    },
}


class GrowthPlanner:
    """Creates growth roadmaps with revenue targets and milestones.

    Usage:
        planner = GrowthPlanner()
        roadmap = planner.create_roadmap(
            current_revenue=10000,
            target_revenue=25000,
            months=6,
        )
    """

    def create_roadmap(
        self,
        current_revenue: float,
        target_revenue: float,
        months: int = 6,
        current_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a growth roadmap from current to target revenue."""
        # Defensive coercion. Pre-audit ``current_revenue <= 0``
        # crashed with TypeError on None / non-numeric inputs.
        # Audit pass 51.
        current_revenue = safe_float(current_revenue)
        target_revenue = safe_float(target_revenue)
        months = safe_int(months, default=6)
        if months <= 0:
            months = 6
        if current_revenue <= 0:
            return {"status": "error", "error": "Current revenue must be positive"}
        if target_revenue <= current_revenue:
            return {"status": "error", "error": "Target must exceed current revenue"}

        growth_needed = (target_revenue / current_revenue) - 1
        monthly_growth = (target_revenue / current_revenue) ** (1 / months) - 1

        # Generate monthly milestones
        milestones = []
        revenue = current_revenue
        for month in range(1, months + 1):
            revenue *= (1 + monthly_growth)
            milestones.append({
                "month": month,
                "target_revenue": round(revenue, 2),
                "growth_from_start": round((revenue / current_revenue - 1) * 100, 1),
                "monthly_growth": round(monthly_growth * 100, 1),
            })

        # Recommend growth levers
        levers = self._recommend_levers(growth_needed, months, current_metrics)

        # Budget allocation
        stage = self._determine_stage(current_revenue)
        budget = self._allocate_budget(current_revenue, stage)

        # Risk assessment
        risk = self._assess_growth_risk(growth_needed, months)

        return {
            "current_revenue": current_revenue,
            "target_revenue": target_revenue,
            "months": months,
            "total_growth_needed": f"+{growth_needed * 100:.0f}%",
            "monthly_growth_rate": f"+{monthly_growth * 100:.1f}%/month",
            "milestones": milestones,
            "recommended_levers": levers,
            "budget_allocation": budget,
            "stage": stage,
            "risk_assessment": risk,
        }

    def backtrack_requirements(
        self,
        target_revenue: float,
        months: int,
        current_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Backtrack from revenue target to required metric improvements.

        Revenue = Traffic × Conversion × AOV × Repeat Rate
        """
        target_revenue = safe_float(target_revenue)
        months = safe_int(months, default=6)
        if months <= 0:
            months = 6
        if not isinstance(current_metrics, dict):
            current_metrics = {}
        # Pre-audit ``safe_float(metric.get("key", default))``
        # used the default only when the key was MISSING —
        # present-but-None coerced to 0, producing a
        # zero-revenue error below. Use ``or default`` pattern.
        # Audit pass 51.
        traffic = safe_float(current_metrics.get("monthly_traffic") or 10000)
        cvr = safe_float(current_metrics.get("conversion_rate") or 0.02)
        aov = safe_float(current_metrics.get("aov") or 50)
        repeat_rate = safe_float(current_metrics.get("repeat_rate") or 1.2)

        current_revenue = traffic * cvr * aov * repeat_rate
        if current_revenue <= 0:
            return {"status": "error", "error": "Current metrics produce zero revenue"}
        if target_revenue <= 0:
            return {"status": "error", "error": "Target revenue must be positive"}

        growth_factor = target_revenue / current_revenue

        # Distribute growth evenly across 4 levers
        per_lever = growth_factor ** 0.25  # 4th root

        required_traffic = round(traffic * per_lever)
        required_cvr = round(cvr * per_lever, 4)
        required_aov = round(aov * per_lever, 2)
        required_repeat = round(repeat_rate * per_lever, 2)

        return {
            "target_revenue": target_revenue,
            "current_revenue": round(current_revenue, 2),
            "growth_factor": round(growth_factor, 2),
            "required_improvements": {
                "traffic": {"current": traffic, "required": required_traffic, "lift": f"+{(per_lever - 1) * 100:.0f}%"},
                "conversion_rate": {"current": cvr, "required": required_cvr, "lift": f"+{(per_lever - 1) * 100:.0f}%"},
                "aov": {"current": aov, "required": required_aov, "lift": f"+{(per_lever - 1) * 100:.0f}%"},
                "repeat_rate": {"current": repeat_rate, "required": required_repeat, "lift": f"+{(per_lever - 1) * 100:.0f}%"},
            },
            "insight": (
                f"To reach ${target_revenue:,.0f}/month, each lever needs ~+{(per_lever - 1) * 100:.0f}% improvement. "
                f"Compounding means each lever does less work than the total growth needed."
            ),
        }

    def _recommend_levers(self, growth_needed, months, metrics):
        recommended = []
        for name, config in GROWTH_LEVERS.items():
            min_lift, max_lift = config["typical_lift"]
            mid_lift = (min_lift + max_lift) / 2

            if growth_needed <= 0.30:
                # Small growth — focus on quick wins
                if config["effort"] in ("low", "medium"):
                    recommended.append({
                        "lever": name,
                        "expected_lift": f"+{mid_lift * 100:.0f}%",
                        "effort": config["effort"],
                        "time": config["time_to_impact"],
                        "tactics": config["tactics"][:3],
                    })
            else:
                # Ambitious growth — need everything
                recommended.append({
                    "lever": name,
                    "expected_lift": f"+{mid_lift * 100:.0f}%",
                    "effort": config["effort"],
                    "time": config["time_to_impact"],
                    "tactics": config["tactics"][:3],
                })

        # Use ``.get()`` with default so an unexpected effort
        # value doesn't crash the sort with KeyError. Audit
        # pass 51.
        effort_rank = {"low": 0, "medium": 1, "high": 2, "very_high": 3}
        recommended.sort(key=lambda r: effort_rank.get(r.get("effort", ""), 99))
        return recommended[:5]

    def _determine_stage(self, revenue):
        if revenue < 10000:
            return "early_stage"
        elif revenue < 50000:
            return "growth_stage"
        elif revenue < 200000:
            return "scale_stage"
        return "enterprise_stage"

    def _allocate_budget(self, revenue, stage):
        template = BUDGET_TEMPLATES.get(stage, BUDGET_TEMPLATES["growth_stage"])
        marketing_budget = revenue * 0.15  # 15% of revenue
        allocation = {}
        for category, pct in template.items():
            if category == "description":
                continue
            allocation[category] = {
                "pct": f"{pct * 100:.0f}%",
                "monthly_amount": round(marketing_budget * pct, 2),
            }
        allocation["_total_monthly"] = round(marketing_budget, 2)
        allocation["_stage"] = stage
        allocation["_description"] = template.get("description", "")
        return allocation

    def _assess_growth_risk(self, growth_needed, months):
        monthly = (1 + growth_needed) ** (1 / months) - 1
        if monthly > 0.15:
            return {"level": "very_high", "monthly_rate": f"{monthly * 100:.1f}%", "note": "Over 15%/month growth is very aggressive. Requires significant investment and perfect execution."}
        elif monthly > 0.08:
            return {"level": "high", "monthly_rate": f"{monthly * 100:.1f}%", "note": "8-15%/month is ambitious but achievable with focused execution."}
        elif monthly > 0.04:
            return {"level": "medium", "monthly_rate": f"{monthly * 100:.1f}%", "note": "4-8%/month is healthy growth. Focus on compound improvements."}
        return {"level": "low", "monthly_rate": f"{monthly * 100:.1f}%", "note": "Under 4%/month is conservative. Good for sustainable, low-risk growth."}
