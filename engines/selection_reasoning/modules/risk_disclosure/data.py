"""Risk Disclosure — reference data: templates, mitigation library, worst-case factors.

Provides structured data for risk disclosure including pre-built mitigation
strategies for common risk types, worst-case loss calculation factors,
and disclosure formatting templates.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Risk disclosure templates by severity
# ---------------------------------------------------------------------------
RISK_TEMPLATES: dict[str, dict[str, str]] = {
    "critical": {
        "header": "CRITICAL RISK: {name}",
        "body": "{description} This risk could result in significant financial loss.",
        "urgency": "Requires immediate attention before proceeding.",
    },
    "high": {
        "header": "HIGH RISK: {name}",
        "body": "{description} This risk should be actively managed.",
        "urgency": "Address before or during launch.",
    },
    "moderate": {
        "header": "MODERATE RISK: {name}",
        "body": "{description} Monitor and adjust as needed.",
        "urgency": "Track during launch phase.",
    },
    "low": {
        "header": "LOW RISK: {name}",
        "body": "{description} Minimal impact expected.",
        "urgency": "No special action required.",
    },
}

# ---------------------------------------------------------------------------
# Mitigation strategy library — specific plans for known risk types
# ---------------------------------------------------------------------------
MITIGATION_LIBRARY: dict[str, dict[str, Any]] = {
    "composite_risk": {
        "strategy": "Diversified risk reduction across all identified factors",
        "actions": [
            "Start with minimum viable order quantity",
            "Set clear performance thresholds for the first 30 days",
            "Establish stop-loss criteria: exit if losses exceed 15% of investment",
            "Review all risk factors weekly during the first month",
        ],
        "timeline": "Before launch and weeks 1-4",
        "estimated_cost": "5-10% of investment for risk management overhead",
        "effectiveness": "moderate to high",
    },
    "high_competition": {
        "strategy": "Differentiation and niche positioning to avoid direct competition",
        "actions": [
            "Identify 2-3 differentiators (bundling, branding, superior listing)",
            "Price strategically — avoid the race to the bottom",
            "Focus on underserved segments within the market",
            "Invest in brand identity from day one",
        ],
        "timeline": "Before listing goes live",
        "estimated_cost": "$200-500 for branding and listing optimization",
        "effectiveness": "high if differentiators are genuine",
    },
    "low_demand": {
        "strategy": "Demand validation and marketing-driven growth",
        "actions": [
            "Run a small PPC campaign ($50-100) to validate actual demand",
            "Test multiple keywords and listing variations",
            "Consider adjacent markets or product variations",
            "Set a 30-day demand validation window before scaling",
        ],
        "timeline": "Weeks 1-4 (validation phase)",
        "estimated_cost": "$100-300 for demand testing",
        "effectiveness": "moderate — cannot create demand that does not exist",
    },
    "thin_margins": {
        "strategy": "Cost optimization and pricing discipline",
        "actions": [
            "Negotiate supplier pricing for volume discounts",
            "Optimize FBA fees by adjusting packaging dimensions",
            "Set a minimum acceptable margin and do not go below it",
            "Explore bundling to increase average order value",
        ],
        "timeline": "Before first order and ongoing",
        "estimated_cost": "minimal — primarily negotiation effort",
        "effectiveness": "moderate — some costs are fixed",
    },
    "low_confidence": {
        "strategy": "Data enrichment before committing significant resources",
        "actions": [
            "Re-run missing engines to fill data gaps",
            "Manually verify key assumptions (pricing, demand)",
            "Start with a test-size investment until confidence improves",
            "Set a data quality checkpoint at day 14",
        ],
        "timeline": "Before committing full investment",
        "estimated_cost": "time investment — 2-4 hours of research",
        "effectiveness": "high — more data reduces uncertainty significantly",
    },
    "declining_trend": {
        "strategy": "Short-term opportunity capture with exit plan",
        "actions": [
            "Treat as a short-term play — do not overinvest in inventory",
            "Plan inventory to sell through within 60-90 days",
            "Monitor trend indicators weekly for acceleration of decline",
            "Have a liquidation strategy ready if trend worsens",
        ],
        "timeline": "Immediate — declining trends reward fast movers",
        "estimated_cost": "minimal beyond standard operations",
        "effectiveness": "moderate — trend reversal is unlikely",
    },
    "general_market_risk": {
        "strategy": "Standard risk management practices",
        "actions": [
            "Maintain adequate cash reserves (20% of investment)",
            "Diversify across multiple products when possible",
            "Stay informed about market and regulatory changes",
        ],
        "timeline": "Ongoing",
        "estimated_cost": "none beyond opportunity cost of reserves",
        "effectiveness": "high for standard market fluctuations",
    },
}

# ---------------------------------------------------------------------------
# Worst-case calculation factors by severity
# ---------------------------------------------------------------------------
WORST_CASE_FACTORS: dict[str, dict[str, Any]] = {
    "critical": {
        "loss_percentage": 80,
        "scenario": (
            "In the worst case, you could lose ${loss:,.0f} ({pct:.0f}% of your "
            "${investment:,.0f} investment). This assumes the primary risk "
            "materializes fully and mitigation is only partially effective."
        ),
        "recovery_time": "3-6 months to recover capital",
        "probability": "15-25% if unmitigated",
    },
    "high": {
        "loss_percentage": 50,
        "scenario": (
            "In the worst case, you could lose ${loss:,.0f} ({pct:.0f}% of your "
            "${investment:,.0f} investment). This assumes high-severity risks "
            "materialize without full mitigation."
        ),
        "recovery_time": "2-4 months to recover capital",
        "probability": "10-20% if unmitigated",
    },
    "moderate": {
        "loss_percentage": 25,
        "scenario": (
            "In the worst case, you could lose ${loss:,.0f} ({pct:.0f}% of your "
            "${investment:,.0f} investment). Moderate risks are manageable with "
            "proper monitoring."
        ),
        "recovery_time": "1-2 months to recover capital",
        "probability": "5-10% with standard precautions",
    },
    "low": {
        "loss_percentage": 10,
        "scenario": (
            "In the worst case, you could lose ${loss:,.0f} ({pct:.0f}% of your "
            "${investment:,.0f} investment). Low-risk scenarios rarely materialize "
            "into significant losses."
        ),
        "recovery_time": "2-4 weeks to recover capital",
        "probability": "Under 5%",
    },
}
