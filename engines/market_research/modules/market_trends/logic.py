"""Market trends decision logic — should we follow this trend?

Not all trends are worth chasing. Logic determines:
  - Is this trend sustainable or a fad?
  - Are we early enough to capture value?
  - Does the trend match our capabilities?
"""
from __future__ import annotations

from typing import Any


# Trend timing windows
TIMING_WINDOWS = {
    "too_early": {
        "description": "Trend is emerging but market not proven yet",
        "risk": "high",
        "reward": "very_high",
        "action": "Monitor closely, prepare to enter when signals strengthen",
    },
    "early_mover": {
        "description": "Trend confirmed, competition still low",
        "risk": "medium",
        "reward": "high",
        "action": "Enter NOW — best window for first-mover advantage",
    },
    "growth_phase": {
        "description": "Trend established, competition building",
        "risk": "medium",
        "reward": "medium",
        "action": "Enter with differentiation — need unique angle",
    },
    "mature": {
        "description": "Trend peaked, market saturated",
        "risk": "low",
        "reward": "low",
        "action": "Only enter with strong competitive advantage or niche focus",
    },
    "declining": {
        "description": "Trend fading, market shrinking",
        "risk": "high",
        "reward": "very_low",
        "action": "Avoid — resources better spent elsewhere",
    },
}


def assess_trend_timing(trend_data: dict[str, Any]) -> dict[str, Any]:
    """Determine where we are in the trend lifecycle.

    Uses trend score + momentum + competition signals.
    """
    score = trend_data.get("trend_score", 0)
    level = trend_data.get("trend_level", "stable")
    confidence = trend_data.get("confidence", "low")

    # Determine timing phase
    if level == "exploding" and confidence in ("low", "medium"):
        phase = "too_early"
    elif level == "exploding" and confidence == "high":
        phase = "early_mover"
    elif level == "growing":
        phase = "growth_phase" if score < 70 else "early_mover"
    elif level == "stable":
        phase = "mature"
    elif level in ("declining", "dying"):
        phase = "declining"
    else:
        phase = "growth_phase"

    window = TIMING_WINDOWS[phase]

    return {
        "timing_phase": phase,
        "description": window["description"],
        "risk_level": window["risk"],
        "reward_potential": window["reward"],
        "recommended_action": window["action"],
        "urgency": _calculate_urgency(phase, score),
    }


def evaluate_trend_sustainability(signals: dict[str, Any]) -> dict[str, Any]:
    """Is this a sustainable trend or a short-lived fad?

    Sustainable trends:
      - Multiple signal types (search + social + marketplace)
      - Gradual growth (not spike)
      - Review activity growing (people actually buying, not just talking)

    Fads:
      - Single signal spike (e.g., TikTok viral only)
      - Explosive growth > 300% (often unsustainable)
      - No review growth (hype without purchase)
    """
    search_growth = signals.get("search_growth_pct", 0)
    social_growth = signals.get("social_mentions_growth", 0)
    review_growth = signals.get("review_volume_growth", 0)
    new_products = signals.get("new_products_launched", 0)

    sustainability_score = 0
    factors = []

    # Multi-signal confirmation (most important)
    active_signals = sum(1 for v in [search_growth, social_growth, review_growth] if v and v > 10)
    if active_signals >= 3:
        sustainability_score += 35
        factors.append("All 3 signal types confirm growth — strong sustainability")
    elif active_signals >= 2:
        sustainability_score += 25
        factors.append("2 signal types confirm — moderate sustainability")
    elif active_signals == 1:
        sustainability_score += 10
        factors.append("Only 1 signal type — could be a fad")
    else:
        factors.append("No strong signals — no clear trend")

    # Review growth = people are buying (not just browsing/talking)
    if review_growth > 20:
        sustainability_score += 25
        factors.append(f"Review volume up {review_growth:.0f}% — real purchasing activity")
    elif review_growth > 5:
        sustainability_score += 15
        factors.append("Moderate review growth — some purchasing")
    elif review_growth <= 0:
        sustainability_score -= 10
        factors.append("No review growth — people may be talking but not buying")

    # Gradual vs spike (gradual is more sustainable)
    if 20 < search_growth < 100:
        sustainability_score += 20
        factors.append("Gradual search growth — healthy, sustainable pace")
    elif search_growth > 300:
        sustainability_score -= 10
        factors.append(f"Explosive search spike ({search_growth:.0f}%) — likely unsustainable fad")
    elif search_growth > 100:
        sustainability_score += 10
        factors.append("Strong search growth — watch for plateau")

    # New product launches = supply responding to demand
    if 10 < new_products < 100:
        sustainability_score += 20
        factors.append(f"{new_products} new products — supply responding to demand (good sign)")
    elif new_products > 200:
        sustainability_score -= 5
        factors.append(f"{new_products} new products — market may be getting crowded")

    sustainability_score = max(0, min(100, sustainability_score))

    if sustainability_score >= 70:
        verdict = "sustainable"
    elif sustainability_score >= 40:
        verdict = "likely_sustainable"
    elif sustainability_score >= 20:
        verdict = "uncertain"
    else:
        verdict = "likely_fad"

    return {
        "sustainability_score": sustainability_score,
        "verdict": verdict,
        "factors": factors,
    }


def should_follow_trend(
    trend_data: dict[str, Any],
    sustainability: dict[str, Any],
    store_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Final decision: should we follow this trend?

    Combines trend strength, timing, sustainability, and store capabilities.
    """
    trend_score = trend_data.get("trend_score", 0)
    timing = assess_trend_timing(trend_data)
    sustainability_score = sustainability.get("sustainability_score", 50)
    sus_verdict = sustainability.get("verdict", "uncertain")

    # Weighted decision score
    score = (
        trend_score * 0.35 +
        sustainability_score * 0.35 +
        (80 if timing["timing_phase"] in ("early_mover", "growth_phase") else 30) * 0.30
    )
    score = max(0, min(100, score))

    # Hard blockers
    if timing["timing_phase"] == "declining":
        return {
            "decision": "skip",
            "score": score,
            "reason": "Trend is declining — too late to enter",
            "timing": timing,
        }

    if sus_verdict == "likely_fad":
        return {
            "decision": "skip",
            "score": score,
            "reason": "Likely a fad — unsustainable growth pattern",
            "timing": timing,
        }

    # Decision
    if score >= 70:
        decision = "follow"
        reason = "Strong trend with good sustainability and timing"
    elif score >= 45:
        decision = "consider"
        reason = "Moderate opportunity — needs strong execution"
    else:
        decision = "skip"
        reason = "Weak trend or poor timing"

    return {
        "decision": decision,
        "score": round(score, 1),
        "reason": reason,
        "timing": timing,
        "sustainability": sus_verdict,
    }


def _calculate_urgency(phase: str, score: float) -> str:
    """How urgently should we act?"""
    if phase == "early_mover" and score > 70:
        return "act_now"
    if phase == "early_mover":
        return "act_soon"
    if phase == "growth_phase":
        return "plan_and_enter"
    if phase == "too_early":
        return "monitor"
    return "no_rush"
