"""Emerging niches decision logic — assess viability, timeline, and entry timing.

Not every signal cluster is a real niche. This module separates signal from noise,
estimates when niches go mainstream, and recommends when to enter.
"""
from __future__ import annotations
from typing import Any

from .data import SIGNAL_WEIGHTS, NICHE_LIFECYCLE_STAGES, TRIGGER_SPEEDS


def assess_niche_viability(niche_data: dict[str, Any]) -> dict[str, Any]:
    """Determine whether a detected niche is real or noise.

    A viable niche needs:
      - Multiple corroborating signal types (not just one)
      - Signal strength above noise floor
      - A plausible trigger event (why NOW?)
      - Growth trajectory (signals increasing, not flat)
    """
    signals = niche_data.get("signals", {})
    trigger = niche_data.get("trigger", "unknown")

    # 1. Signal diversity — how many sources confirm this niche?
    active_signals = {k: v for k, v in signals.items() if v and v > 0}
    diversity = len(active_signals)
    diversity_score = min(100, diversity * 25)  # 4+ sources = 100

    # 2. Weighted strength — are the signals meaningful?
    weighted_strength = sum(
        signals.get(sig, 0) * weight for sig, weight in SIGNAL_WEIGHTS.items()
    )
    strength_score = min(100, weighted_strength * 2.5)

    # 3. Signal agreement — do different sources tell the same story?
    values = list(active_signals.values())
    if len(values) >= 2:
        avg = sum(values) / len(values)
        variance = sum((v - avg) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
        # Lower std_dev relative to mean = higher agreement
        agreement_score = max(0, min(100, 100 - (std_dev / max(avg, 1)) * 100))
    else:
        agreement_score = 0

    # 4. Trigger plausibility — known triggers are more reliable
    trigger_info = TRIGGER_SPEEDS.get(trigger, {})
    trigger_score = 80 if trigger_info.get("predictability") == "high" else \
                    60 if trigger_info.get("predictability") == "medium" else \
                    30 if trigger_info.get("predictability") == "low" else 15

    # Composite viability score
    viability = round(
        diversity_score * 0.30 +
        strength_score * 0.35 +
        agreement_score * 0.20 +
        trigger_score * 0.15
    )

    if viability >= 70:
        verdict = "viable"
        reasoning = "Strong multi-source signals with clear trigger — real niche"
    elif viability >= 45:
        verdict = "plausible"
        reasoning = "Some supporting signals but needs more validation"
    elif viability >= 25:
        verdict = "uncertain"
        reasoning = "Weak signals — could be noise, monitor for 4-8 weeks"
    else:
        verdict = "noise"
        reasoning = "Insufficient evidence — likely not a real niche"

    return {
        "verdict": verdict,
        "viability_score": viability,
        "reasoning": reasoning,
        "factors": {
            "signal_diversity": {"score": round(diversity_score), "active_sources": diversity},
            "signal_strength": {"score": round(strength_score), "weighted_value": round(weighted_strength, 1)},
            "signal_agreement": {"score": round(agreement_score)},
            "trigger_plausibility": {"score": trigger_score, "trigger": trigger},
        },
    }


def estimate_niche_timeline(signals: dict[str, Any]) -> dict[str, Any]:
    """Estimate when this niche will reach each lifecycle stage.

    Uses signal velocity, trigger type, and historical patterns to project
    months until the niche transitions between stages.
    """
    current_maturity = signals.get("maturity", "pre-market")
    trigger = signals.get("trigger", "technology")
    signal_values = signals.get("signals", {})

    # Average signal strength indicates how far along the niche is
    active_vals = [v for v in signal_values.values() if v and v > 0]
    avg_strength = sum(active_vals) / max(len(active_vals), 1)

    # Trigger speed affects how fast the niche moves
    trigger_info = TRIGGER_SPEEDS.get(trigger, TRIGGER_SPEEDS["technology"])
    speed_factor = {"very_fast": 0.5, "fast": 0.75, "medium": 1.0, "slow": 1.5}.get(
        trigger_info.get("speed", "medium"), 1.0
    )

    # Build timeline from current stage forward
    stages = ["pre-market", "early", "growing", "mainstream"]
    current_idx = stages.index(current_maturity) if current_maturity in stages else 0
    timeline: list[dict[str, Any]] = []
    cumulative_months = 0

    for i, stage in enumerate(stages):
        stage_info = NICHE_LIFECYCLE_STAGES[stage]
        min_dur, max_dur = stage_info["duration_months"]

        # Stronger signals = faster progression
        strength_modifier = max(0.6, 1.0 - (avg_strength / 200))
        est_months = round((min_dur + max_dur) / 2 * speed_factor * strength_modifier)

        if i <= current_idx:
            timeline.append({
                "stage": stage,
                "status": "current" if i == current_idx else "passed",
                "months_from_now": 0,
            })
        else:
            cumulative_months += est_months
            timeline.append({
                "stage": stage,
                "status": "projected",
                "months_from_now": cumulative_months,
                "estimated_duration_months": est_months,
            })

    mainstream_months = cumulative_months if cumulative_months > 0 else "already_mainstream"

    return {
        "current_stage": current_maturity,
        "months_to_mainstream": mainstream_months,
        "timeline": timeline,
        "confidence": "high" if avg_strength > 40 else "medium" if avg_strength > 20 else "low",
        "speed_driver": trigger,
    }


# Recommended max investment by entry timing
MAX_INVESTMENT_BY_TIMING: dict[str, int] = {
    "enter_now": 500,
    "wait_3_months": 200,      # Monitoring/prep costs only
    "wait_6_months": 50,       # Just tracking costs
    "too_late": 0,
}


def recommend_entry_timing(niche: dict[str, Any]) -> dict[str, Any]:
    """Recommend when to enter: now, wait 3 months, or wait 6 months.

    Decision factors:
      - Current maturity stage (earlier = more risk, more reward)
      - Viability assessment (is it real?)
      - Competition window (how long until crowded?)
      - Required investment level
    """
    viability = assess_niche_viability(niche)
    timeline = estimate_niche_timeline(niche)
    maturity = niche.get("maturity", "pre-market")

    viability_score = viability["viability_score"]
    months_to_mainstream = timeline.get("months_to_mainstream", 36)
    if isinstance(months_to_mainstream, str):
        months_to_mainstream = 0

    # Entry timing logic
    if maturity == "pre-market":
        if viability_score >= 60:
            timing = "enter_now"
            action = "Build audience and test with micro-product ($200 validation)"
            risk = "medium-high"
            potential_reward = "first-mover advantage, 60-80% margins"
        else:
            timing = "wait_6_months"
            action = "Monitor signals monthly, re-evaluate when 2+ signals strengthen"
            risk = "low (just monitoring cost)"
            potential_reward = "reduced risk if niche validates"

    elif maturity == "early":
        if viability_score >= 50:
            timing = "enter_now"
            action = "Launch MVP product, capture early adopters, build reviews"
            risk = "medium"
            potential_reward = "strong positioning before competition arrives"
        else:
            timing = "wait_3_months"
            action = "Prepare supply chain, start content, launch when signals strengthen"
            risk = "low-medium"
            potential_reward = "better data for product decisions"

    elif maturity == "growing":
        if months_to_mainstream > 12:
            timing = "enter_now"
            action = "Launch differentiated product, scale marketing fast"
            risk = "medium (competition exists)"
            potential_reward = "proven demand, still room for new entrants"
        else:
            timing = "wait_3_months"
            action = "Find a sub-niche within this space to differentiate"
            risk = "medium-high (narrowing window)"
            potential_reward = "sub-niche focus reduces competition"

    else:  # mainstream
        timing = "too_late"
        action = "Find a sub-niche or move to the next emerging category"
        risk = "high (saturated market)"
        potential_reward = "limited — competing on price/operations only"

    return {
        "timing": timing,
        "action": action,
        "risk": risk,
        "potential_reward": potential_reward,
        "viability_score": viability_score,
        "months_to_mainstream": months_to_mainstream,
        "maturity": maturity,
        "investment_cap": MAX_INVESTMENT_BY_TIMING.get(timing, 500),
    }
