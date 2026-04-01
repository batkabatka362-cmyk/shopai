"""Saturation decision logic — what to do when market is saturated.

Not all saturated markets are bad. This module decides:
  - Can we enter despite saturation? (niche within niche)
  - What strategy works in saturated markets?
  - When should we exit a saturating market?
"""
from __future__ import annotations

from typing import Any


def decide_entry_strategy(analysis: dict[str, Any]) -> dict[str, Any]:
    """Given saturation analysis, recommend entry strategy.

    Even saturated markets have openings — if you know where to look.
    """
    level = analysis.get("level", "unknown")
    index = analysis.get("saturation_index", 50)
    warnings = analysis.get("warnings", [])

    if level == "oversaturated":
        return {
            "strategy": "avoid_or_sub_niche",
            "approach": [
                "Don't enter the broad market — it's full",
                "Find a sub-niche within the category that's underserved",
                "Example: 'yoga mats' is saturated → 'extra thick yoga mats for bad knees' is not",
                "Target long-tail keywords competitors ignore",
                "Build brand community before selling (content-first approach)",
            ],
            "estimated_success_rate": 0.15,
            "time_to_roi": "12-18 months",
            "required_investment": "high",
        }

    if level == "highly_saturated":
        return {
            "strategy": "differentiation_required",
            "approach": [
                "Enter ONLY with clearly differentiated product",
                "Your product must be visibly different (design, material, feature)",
                "Price premium OK if value is clear",
                "Heavy content marketing (education, comparison, reviews)",
                "Influencer partnerships to bypass ad competition",
            ],
            "estimated_success_rate": 0.30,
            "time_to_roi": "6-12 months",
            "required_investment": "medium-high",
        }

    if level == "moderately_saturated":
        return {
            "strategy": "quality_execution",
            "approach": [
                "Standard entry possible with good execution",
                "Better product photos than competitors",
                "SEO-optimized listings (title, bullets, backend keywords)",
                "Aggressive review collection (post-purchase email sequence)",
                "Balanced ad strategy (search + social)",
            ],
            "estimated_success_rate": 0.50,
            "time_to_roi": "3-6 months",
            "required_investment": "medium",
        }

    if level == "lightly_saturated":
        return {
            "strategy": "capture_quickly",
            "approach": [
                "Good entry window — competition manageable",
                "Focus on establishing presence fast",
                "SEO + content to build organic traffic",
                "Moderate ad spend to accelerate",
                "Build reviews quickly for social proof",
            ],
            "estimated_success_rate": 0.65,
            "time_to_roi": "1-3 months",
            "required_investment": "low-medium",
        }

    # Unsaturated
    return {
        "strategy": "first_mover",
        "approach": [
            "Low competition — verify demand exists first",
            "If demand confirmed, move FAST",
            "Establish category presence (become the go-to brand)",
            "Content + SEO to own the search terms",
            "Low ad spend needed initially",
        ],
        "estimated_success_rate": 0.70,
        "time_to_roi": "2-4 weeks",
        "required_investment": "low",
    }


def find_sub_niche_opportunities(
    analysis: dict[str, Any],
    parent_category: str,
) -> dict[str, Any]:
    """When main category is saturated, find sub-niches that aren't.

    The magic: broad category saturated → specific angle unsaturated.
    """
    index = analysis.get("saturation_index", 50)

    # Sub-niche strategies by saturation level
    if index < 40:
        return {
            "needed": False,
            "reason": "Main category not saturated — sub-niche not required",
        }

    sub_niche_angles = {
        "demographic": {
            "description": "Target specific customer group",
            "examples": [
                f"{parent_category} for beginners",
                f"{parent_category} for seniors",
                f"{parent_category} for kids",
                f"Professional-grade {parent_category}",
                f"Budget {parent_category} for students",
            ],
        },
        "use_case": {
            "description": "Target specific situation",
            "examples": [
                f"{parent_category} for small spaces",
                f"Travel-friendly {parent_category}",
                f"{parent_category} for outdoor use",
                f"Heavy-duty {parent_category}",
            ],
        },
        "material_feature": {
            "description": "Differentiate by material or unique feature",
            "examples": [
                f"Organic/natural {parent_category}",
                f"Sustainable/eco-friendly {parent_category}",
                f"Handmade {parent_category}",
                f"{parent_category} with [unique feature]",
            ],
        },
        "problem_specific": {
            "description": "Solve a specific problem others don't",
            "examples": [
                f"{parent_category} for [specific condition]",
                f"Allergen-free {parent_category}",
                f"Extra-durable {parent_category}",
            ],
        },
    }

    return {
        "needed": True,
        "parent_saturation": index,
        "reason": f"Parent category is {analysis.get('level', '?')} — sub-niche approach recommended",
        "angles": sub_niche_angles,
        "selection_criteria": [
            "Sub-niche must have search volume (verify on Google Trends)",
            "Sub-niche must have fewer than 10-15 direct competitors",
            "Sub-niche must have viable margin (don't go too narrow that volume = 0)",
            "You must have authentic connection to the niche (or be able to build one)",
        ],
    }


def assess_exit_signals(
    current_metrics: dict[str, Any],
    previous_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect if a market you're IN is becoming too saturated to stay.

    Exit signals for an existing store:
    """
    margin = current_metrics.get("current_margin", 0)
    margin_trend = current_metrics.get("margin_trend_pct", 0)
    rank_trend = current_metrics.get("rank_trend", 0)
    cpc_trend = current_metrics.get("cpc_trend_pct", 0)
    new_competitors = current_metrics.get("new_competitors_monthly", 0)

    exit_signals = []

    if margin < 15:
        exit_signals.append({"signal": "margin_critical", "severity": "high", "detail": f"Margin at {margin}% — below sustainable level"})
    if margin_trend < -5:
        exit_signals.append({"signal": "margin_declining", "severity": "high", "detail": f"Margin declining {margin_trend}% — competition squeezing"})
    if cpc_trend > 20:
        exit_signals.append({"signal": "cpc_exploding", "severity": "medium", "detail": f"CPCs up {cpc_trend}% — ad costs unsustainable"})
    if new_competitors > 10:
        exit_signals.append({"signal": "competitor_flood", "severity": "medium", "detail": f"{new_competitors} new competitors/month — market flooding"})
    if rank_trend < -10:
        exit_signals.append({"signal": "rank_declining", "severity": "medium", "detail": f"Search ranking declining — losing visibility"})

    if len(exit_signals) >= 3:
        verdict = "exit"
        action = "Begin exit strategy: clearance inventory, shift resources to better market"
    elif len(exit_signals) >= 2:
        verdict = "prepare_exit"
        action = "Develop exit plan. Reduce inventory orders. Test alternative markets."
    elif len(exit_signals) >= 1:
        verdict = "monitor"
        action = "Watch closely. Don't expand. Maintain but don't invest."
    else:
        verdict = "stay"
        action = "Market position healthy. Continue current strategy."

    return {
        "verdict": verdict,
        "action": action,
        "exit_signals": exit_signals,
        "signal_count": len(exit_signals),
    }
