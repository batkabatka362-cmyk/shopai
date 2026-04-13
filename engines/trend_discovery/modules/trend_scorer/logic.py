"""Trend scorer decision logic — ranking, action, comparison, and portfolio building.

Turns raw scored trends into actionable decisions:
  - Which trends to pursue (and in what order)
  - What action to take on each trend
  - How to compare two competing trends
  - How to build a diversified portfolio of trend bets
"""
from __future__ import annotations

from typing import Any

from .data import PORTFOLIO_RULES, SIGNAL_WEIGHTS


def rank_trends(trend_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank multiple scored trends by composite score and confidence.

    Trends with higher composite scores rank first. When scores are tied,
    higher confidence wins. Signal count is the third tiebreaker.
    """
    if not trend_list:
        return []

    ranked = []
    for trend in trend_list:
        score = trend.get("composite_score", 0)
        confidence = trend.get("confidence", 0)
        signal_count = trend.get("signal_count", 0)
        # Effective rank score: composite weighted by confidence and signal breadth
        rank_score = score * (0.6 + confidence * 0.3) + signal_count * 3
        ranked.append({**trend, "rank_score": round(rank_score, 1)})

    ranked.sort(key=lambda t: t["rank_score"], reverse=True)

    for i, trend in enumerate(ranked):
        trend["rank"] = i + 1

    return ranked


def decide_trend_action(scored_trend: dict[str, Any]) -> dict[str, Any]:
    """Decide what action to take on a scored trend.

    Returns one of: act_now, prepare, monitor, ignore — with reasoning.
    """
    composite = scored_trend.get("composite_score", 0)
    confidence = scored_trend.get("confidence", 0)
    signal_count = scored_trend.get("signal_count", 0)
    classification = scored_trend.get("classification", "weak")
    agreement = scored_trend.get("signal_agreement", {})
    has_conflict = agreement.get("conflict", False)

    # Act now: high score, high confidence, no conflicts
    if composite >= 70 and confidence >= 0.60 and not has_conflict:
        return {
            "action": "act_now",
            "urgency": "high",
            "reasoning": f"Score {composite} with {confidence:.0%} confidence across {signal_count} signals — strong opportunity",
            "next_steps": [
                "Source or create product immediately",
                "Set up supplier negotiations within 7 days",
                "Prepare marketing assets and listing",
            ],
            "budget_allocation": "40-60% of trend budget",
        }

    # Prepare: good score or decent confidence
    if composite >= 50 and confidence >= 0.40:
        return {
            "action": "prepare",
            "urgency": "medium",
            "reasoning": f"Score {composite} with {confidence:.0%} confidence — promising but not yet certain",
            "next_steps": [
                "Research suppliers and product options",
                "Create 1-2 test products or samples",
                "Build content around the trend for SEO",
            ],
            "budget_allocation": "20-35% of trend budget",
        }

    # Monitor: some signals present
    if composite >= 25 or signal_count >= 2:
        investigate_note = " Signals conflict — investigate why." if has_conflict else ""
        return {
            "action": "monitor",
            "urgency": "low",
            "reasoning": f"Score {composite} with {confidence:.0%} confidence — too early to commit.{investigate_note}",
            "next_steps": [
                "Set up alerts for this trend",
                "Check back weekly for signal changes",
                "Look for confirming data from missing sources",
            ],
            "budget_allocation": "10-20% of trend budget (exploratory only)",
        }

    # Ignore: weak or no signals
    return {
        "action": "ignore",
        "urgency": "none",
        "reasoning": f"Score {composite} with {confidence:.0%} confidence — not a viable trend",
        "next_steps": ["No action needed", "Re-evaluate only if new data surfaces"],
        "budget_allocation": "0%",
    }


def compare_trends(trend_a: dict[str, Any], trend_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two trends and determine which is the better opportunity."""
    score_a = trend_a.get("composite_score", 0)
    score_b = trend_b.get("composite_score", 0)
    conf_a = trend_a.get("confidence", 0)
    conf_b = trend_b.get("confidence", 0)
    sigs_a = trend_a.get("signal_count", 0)
    sigs_b = trend_b.get("signal_count", 0)
    name_a = trend_a.get("trend_name", "Trend A")
    name_b = trend_b.get("trend_name", "Trend B")

    # Weighted comparison: score matters most, then confidence, then signals
    effective_a = score_a * 0.55 + conf_a * 100 * 0.30 + sigs_a * 10 * 0.15
    effective_b = score_b * 0.55 + conf_b * 100 * 0.30 + sigs_b * 10 * 0.15

    advantages_a: list[str] = []
    advantages_b: list[str] = []

    if score_a > score_b:
        advantages_a.append(f"Higher composite score ({score_a} vs {score_b})")
    elif score_b > score_a:
        advantages_b.append(f"Higher composite score ({score_b} vs {score_a})")

    if conf_a > conf_b:
        advantages_a.append(f"Higher confidence ({conf_a:.0%} vs {conf_b:.0%})")
    elif conf_b > conf_a:
        advantages_b.append(f"Higher confidence ({conf_b:.0%} vs {conf_a:.0%})")

    if sigs_a > sigs_b:
        advantages_a.append(f"More signal sources ({sigs_a} vs {sigs_b})")
    elif sigs_b > sigs_a:
        advantages_b.append(f"More signal sources ({sigs_b} vs {sigs_a})")

    if effective_a > effective_b:
        winner = name_a
        margin = effective_a - effective_b
    elif effective_b > effective_a:
        winner = name_b
        margin = effective_b - effective_a
    else:
        winner = "tie"
        margin = 0

    return {
        "winner": winner,
        "margin": round(margin, 1),
        "decisive": margin > 10,
        name_a: {"effective_score": round(effective_a, 1), "advantages": advantages_a},
        name_b: {"effective_score": round(effective_b, 1), "advantages": advantages_b},
        "recommendation": f"Choose {winner}" if winner != "tie" else "Too close to call — consider other factors (category fit, margins)",
    }


def build_trend_portfolio(trends: list[dict[str, Any]], max_bets: int = 3) -> dict[str, Any]:
    """Build a diversified portfolio of trend bets from a list of scored trends.

    Selects the best combination considering score, confidence, and diversification.
    """
    max_bets = min(max_bets, PORTFOLIO_RULES["max_active_bets"])
    if not trends:
        return {"portfolio": [], "total_bets": 0, "strategy": "No viable trends available"}

    # Rank first
    ranked = rank_trends(trends)

    # Greedily select trends favoring diversification
    selected: list[dict[str, Any]] = []
    categories_used: dict[str, int] = {}
    max_same_cat = PORTFOLIO_RULES["diversification"]["max_same_category"]

    for trend in ranked:
        if len(selected) >= max_bets:
            break

        cat = trend.get("category", "uncategorized")
        if categories_used.get(cat, 0) >= max_same_cat:
            continue  # Skip to maintain diversification

        # Assign confidence tier for allocation sizing
        composite = trend.get("composite_score", 0)
        confidence = trend.get("confidence", 0)

        if composite >= 70 and confidence >= 0.60:
            tier = "high"
        elif composite >= 45 and confidence >= 0.40:
            tier = "medium"
        else:
            tier = "low"

        alloc = PORTFOLIO_RULES["allocation_by_confidence"].get(tier, {})
        selected.append({
            "trend_name": trend.get("trend_name", "unknown"),
            "category": cat,
            "composite_score": composite,
            "confidence": confidence,
            "confidence_tier": tier,
            "allocation": alloc.get("description", ""),
            "allocation_range": f"{alloc.get('min_pct', 0):.0%}-{alloc.get('max_pct', 0):.0%}",
            "rank": trend.get("rank", 0),
        })
        categories_used[cat] = categories_used.get(cat, 0) + 1

    # Portfolio summary
    tiers = [s["confidence_tier"] for s in selected]
    has_mix = len(set(tiers)) > 1

    return {
        "portfolio": selected,
        "total_bets": len(selected),
        "categories": list(categories_used.keys()),
        "diversified": has_mix and len(categories_used) > 1,
        "strategy": _portfolio_strategy(selected, has_mix),
    }


def _portfolio_strategy(selected: list[dict[str, Any]], has_mix: bool) -> str:
    """Generate a strategy note for the portfolio."""
    if not selected:
        return "No trends selected — continue monitoring for opportunities"
    if len(selected) == 1:
        return "Single bet — higher risk. Look for additional trends to diversify."
    if has_mix:
        return "Good mix of confidence levels — balanced risk/reward portfolio"
    tiers = [s["confidence_tier"] for s in selected]
    if all(t == "high" for t in tiers):
        return "All high-confidence bets — strong but concentrated. Monitor closely."
    if all(t == "low" for t in tiers):
        return "All exploratory bets — high risk. Consider waiting for stronger signals."
    return "Portfolio assembled — review weekly and rebalance as signals change"
