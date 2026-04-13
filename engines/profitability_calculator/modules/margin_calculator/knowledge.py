"""Margin domain knowledge — what experienced e-commerce operators know.

Hard-won truths about margins that spreadsheets don't tell you:
  - "Contribution margin is the REAL number — gross margin lies"
  - "Below 25% margin = one bad month away from loss"
  - "Volume improves margin through: bulk pricing, shipping rates, negotiation leverage"
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Core margin truths
# --------------------------------------------------------------------------- #
MARGIN_TRUTHS = [
    "Contribution margin is the REAL number — gross margin lies because it hides "
    "variable costs like transaction fees, payment processing, and packaging.",

    "Below 25% contribution margin = one bad month away from loss. A single "
    "ad campaign flop, supplier price increase, or shipping surcharge wipes you out.",

    "The 3x rule: your selling price should be AT LEAST 3x your landed COGS. "
    "Below 3x you are fighting for scraps after marketing and operations.",

    "Margins compress over time. Competition enters, ad costs rise, customers demand "
    "discounts. Price for 5% margin erosion per year.",

    "Shopify takes ~2.9% + $0.30 per transaction. At $30 AOV that is 3.9%. "
    "At $10 AOV that is 5.9%. Low-price products bleed on payment processing alone.",

    "Free shipping is not free. If your product is $29.99 and shipping costs $7, "
    "your real margin dropped 23 percentage points.",

    "Returns destroy margin math. A 10% return rate on a 40% gross margin product "
    "means your effective margin is closer to 30% after restocking and shipping costs.",
]

# --------------------------------------------------------------------------- #
#  Volume-margin relationship
# --------------------------------------------------------------------------- #
VOLUME_INSIGHTS = [
    "Volume improves margin through three levers: bulk pricing (5-15% COGS reduction), "
    "better shipping rates (10-30% shipping cost reduction), and supplier negotiation "
    "leverage (2-8% additional discount at 1000+ units/month).",

    "The breakpoint is usually 500 units/month. Below that, you are paying retail "
    "rates on everything. Above it, suppliers start treating you seriously.",

    "Shipping cost per unit drops ~25% when you move from individual parcels to "
    "pallet shipping. Threshold is typically 100-200 units per shipment.",

    "At 2000+ units/month, consider 3PL. You lose some margin to fulfillment fees "
    "but gain back hours and reduce error rates from 3-5% to under 1%.",
]

# --------------------------------------------------------------------------- #
#  Margin improvement playbook
# --------------------------------------------------------------------------- #
IMPROVEMENT_PLAYBOOK: list[dict[str, Any]] = [
    {
        "action": "Raise prices 5-10%",
        "impact": "Immediate 5-10% gross margin increase",
        "risk": "low",
        "effort": "trivial",
        "detail": "Most Shopify stores underprice. Test a 10% price increase on your "
                  "top 20% products. If conversion drops less than 5%, keep the new price.",
    },
    {
        "action": "Negotiate COGS with current supplier",
        "impact": "3-8% gross margin improvement",
        "risk": "low",
        "effort": "moderate",
        "detail": "Show your order history and growth trajectory. Ask for volume tiers. "
                  "Get quotes from 2-3 competing suppliers as leverage.",
    },
    {
        "action": "Reduce shipping costs via dimensional optimization",
        "impact": "2-5% contribution margin improvement",
        "risk": "low",
        "effort": "moderate",
        "detail": "Redesign packaging to minimize dimensional weight. Smaller boxes = "
                  "lower shipping tiers. A 1-inch reduction in height can save $0.50-$2.00/unit.",
    },
    {
        "action": "Bundle products to increase AOV",
        "impact": "Indirect — fixed costs spread over larger order value",
        "risk": "low",
        "effort": "moderate",
        "detail": "Bundles increase AOV by 20-35%. The per-item fulfillment cost drops "
                  "because you ship one package instead of two.",
    },
    {
        "action": "Switch to private label from reselling",
        "impact": "15-30% gross margin increase",
        "risk": "high",
        "effort": "high",
        "detail": "Private label typically yields 45-60% gross margin vs. 25-35% reselling. "
                  "Requires MOQ commitment, quality control, and brand building.",
    },
    {
        "action": "Reduce return rate through better product pages",
        "impact": "2-6% effective margin recovery",
        "risk": "low",
        "effort": "moderate",
        "detail": "Add size guides, 360-degree photos, and realistic product descriptions. "
                  "Every 1% return rate reduction recovers ~0.5% effective margin.",
    },
    {
        "action": "Optimize ad spend ROAS target",
        "impact": "Variable — can swing net margin by 5-15%",
        "risk": "medium",
        "effort": "high",
        "detail": "Set minimum ROAS at (1 / contribution_margin). If contribution margin "
                  "is 40%, minimum ROAS = 2.5x. Below that, you are buying revenue not profit.",
    },
]


def get_margin_insights() -> dict[str, list[str]]:
    """Return core margin knowledge organized by theme."""
    return {
        "truths": MARGIN_TRUTHS,
        "volume_effects": VOLUME_INSIGHTS,
    }


def get_improvement_playbook(
    current_margin: float | None = None,
) -> list[dict[str, Any]]:
    """Return actionable margin improvement steps, optionally filtered by urgency.

    If current_margin < 25%, prioritize low-effort high-impact actions.
    """
    playbook = list(IMPROVEMENT_PLAYBOOK)
    if current_margin is not None and current_margin < 25.0:
        playbook.sort(key=lambda a: 0 if a["risk"] == "low" else 1)
    return playbook


def get_heuristics() -> list[str]:
    """Return quick margin rules of thumb."""
    return [
        "3x COGS = minimum viable price",
        "Contribution margin > 25% or you are one bad month from loss",
        "Shopify payment processing eats 3-6% depending on AOV",
        "Free shipping? Add shipping cost to price and recalculate margin",
        "Every 1% return rate costs ~0.5% effective margin",
        "Ad spend should never exceed contribution margin per order",
        "Volume discount from suppliers kicks in around 500 units/month",
        "Private label: 45-60% gross. Reselling: 25-35%. Dropship: 15-25%.",
    ]
