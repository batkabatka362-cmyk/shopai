"""Gap finder decision logic — should we pursue this gap?

After detecting gaps, this module decides:
  - Is the gap worth pursuing?
  - Can we fill it profitably?
  - What's the priority among multiple gaps?
  - What product should we create to fill it?
"""
from __future__ import annotations

from typing import Any


def decide_gap_pursuit(gap: dict[str, Any], store_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide whether to pursue a specific market gap.

    Args:
        gap: Single gap from gap_finder output
        store_context: Optional store capabilities {budget, category_expertise, supplier_access}
    """
    ctx = store_context or {}
    score = gap.get("opportunity_score", 0)
    gap_type = gap.get("type", "")

    # Evaluate feasibility
    feasibility = _assess_feasibility(gap_type, ctx)

    # Evaluate profitability potential
    profit_potential = _assess_profit_potential(gap_type, score)

    # Combined decision
    combined = round(score * 0.5 + feasibility["score"] * 0.3 + profit_potential["score"] * 0.2)

    if combined >= 70:
        verdict = "pursue"
        action = _recommended_action(gap_type)
    elif combined >= 45:
        verdict = "investigate"
        action = "Research further before committing resources"
    else:
        verdict = "skip"
        action = "Gap exists but not worth pursuing at this time"

    return {
        "verdict": verdict,
        "combined_score": combined,
        "opportunity": score,
        "feasibility": feasibility,
        "profit_potential": profit_potential,
        "recommended_action": action,
        "gap_type": gap_type,
    }


def prioritize_gaps(gaps: list[dict[str, Any]], max_pursue: int = 3) -> dict[str, Any]:
    """From multiple gaps, pick the best ones to pursue.

    Rule: Don't chase too many gaps at once.
    Focus on top 2-3 with highest combined score.
    """
    decisions = []
    for gap in gaps:
        decision = decide_gap_pursuit(gap)
        decisions.append({**gap, **decision})

    decisions.sort(key=lambda d: d["combined_score"], reverse=True)

    pursue = [d for d in decisions if d["verdict"] == "pursue"][:max_pursue]
    investigate = [d for d in decisions if d["verdict"] == "investigate"]
    skip = [d for d in decisions if d["verdict"] == "skip"]

    return {
        "pursue": pursue,
        "investigate": investigate,
        "skip": skip,
        "total_gaps": len(gaps),
        "pursuing": len(pursue),
        "recommendation": (
            f"Pursue {len(pursue)} gaps. Focus resources on highest-scoring first."
            if pursue else
            "No gaps worth pursuing immediately. Continue monitoring."
        ),
    }


def gap_to_product_spec(gap: dict[str, Any]) -> dict[str, Any]:
    """Convert a gap into a product specification outline.

    "We found a gap → here's what product would fill it."
    """
    gap_type = gap.get("type", "")
    description = gap.get("description", "")

    spec = {
        "gap_source": description,
        "product_requirements": [],
        "positioning": "",
        "price_strategy": "",
        "differentiation": "",
    }

    if gap_type == "quality_gap":
        spec["product_requirements"] = [
            "Higher quality materials than competitors",
            "Better packaging and presentation",
            "Stronger warranty/guarantee",
            "Quality certifications if applicable",
        ]
        spec["positioning"] = "Premium quality in a market of mediocre products"
        spec["price_strategy"] = "Price 20-40% above average — justify with quality"
        spec["differentiation"] = "Quality + customer service + warranty"

    elif gap_type == "price_gap":
        spec["product_requirements"] = [
            "Product that fits the missing price tier",
            "Appropriate quality for the price point",
            "Clear value proposition for the tier",
        ]
        spec["positioning"] = "Fill the underserved price tier"
        spec["price_strategy"] = "Price exactly in the gap zone"
        spec["differentiation"] = "Only option in this price range"

    elif gap_type == "complaint_gap":
        spec["product_requirements"] = [
            f"Fix the core complaint: {description}",
            "Explicitly address the issue in product listing",
            "Collect reviews specifically about the fix",
        ]
        spec["positioning"] = "The product that solved [complaint]"
        spec["price_strategy"] = "Match or slightly above competitor pricing"
        spec["differentiation"] = "Direct answer to customer frustration"

    elif gap_type == "demand_supply_gap":
        spec["product_requirements"] = [
            "Product matching the high-demand search terms",
            "SEO-optimized listing for those keywords",
            "Fast-to-market — speed is competitive advantage",
        ]
        spec["positioning"] = "Meet proven demand that nobody is serving"
        spec["price_strategy"] = "Market rate — focus on availability, not price"
        spec["differentiation"] = "Being present where others aren't"

    elif gap_type == "competitor_weakness":
        spec["product_requirements"] = [
            "Match competitor features",
            "Exceed on their weakest points (reviews show what's weak)",
            "Better photos, descriptions, customer support",
        ]
        spec["positioning"] = "Better version of what already sells"
        spec["price_strategy"] = "Match price, win on value"
        spec["differentiation"] = "Same product, better execution"

    else:
        spec["product_requirements"] = ["Research the gap further before defining requirements"]
        spec["positioning"] = "TBD — need more data"
        spec["price_strategy"] = "TBD"
        spec["differentiation"] = "TBD"

    return spec


def _assess_feasibility(gap_type: str, context: dict[str, Any]) -> dict[str, Any]:
    """How feasible is it to fill this gap?"""
    budget = context.get("budget", "medium")
    expertise = context.get("category_expertise", "low")
    supplier = context.get("supplier_access", False)

    base_scores = {
        "complaint_gap": 80,       # Easy — improve existing product
        "price_gap": 70,           # Moderate — need right sourcing
        "competitor_weakness": 75,  # Moderate — execution challenge
        "quality_gap": 60,         # Hard — quality costs money
        "demand_supply_gap": 65,   # Moderate — speed matters
        "new_market_gap": 40,      # Hard — unproven
    }
    score = base_scores.get(gap_type, 50)

    if budget == "high":
        score = min(100, score + 10)
    if expertise == "high":
        score = min(100, score + 10)
    if supplier:
        score = min(100, score + 10)

    return {
        "score": score,
        "factors": {
            "gap_difficulty": gap_type,
            "budget": budget,
            "expertise": expertise,
            "supplier_access": supplier,
        },
    }


def _assess_profit_potential(gap_type: str, opportunity_score: int) -> dict[str, Any]:
    """How profitable could filling this gap be?"""
    margin_multipliers = {
        "quality_gap": 1.3,         # Premium pricing
        "price_gap": 1.0,           # Standard margins
        "complaint_gap": 1.2,       # Slight premium for better product
        "demand_supply_gap": 1.1,   # Market rate
        "competitor_weakness": 1.0,  # Competitive pricing
        "new_market_gap": 0.8,      # Unknown margins
    }
    multiplier = margin_multipliers.get(gap_type, 1.0)
    score = round(min(100, opportunity_score * multiplier))

    return {
        "score": score,
        "margin_multiplier": multiplier,
        "reasoning": f"Gap type '{gap_type}' typically yields {multiplier}x margin vs average",
    }


def _recommended_action(gap_type: str) -> str:
    """Specific next action per gap type."""
    actions = {
        "demand_supply_gap": "Source product immediately — demand is proven. Speed to market = advantage.",
        "complaint_gap": "Develop improved product that specifically fixes the complaint. Highlight fix in listing.",
        "quality_gap": "Source premium version. Invest in quality photography and detailed descriptions.",
        "competitor_weakness": "Study weak competitors' listings. Create better version with superior content.",
        "price_gap": "Find product that fits the empty price tier. Test with small batch first.",
        "new_market_gap": "Test with minimal inventory. Validate demand before scaling.",
    }
    return actions.get(gap_type, "Research further and develop product spec")
