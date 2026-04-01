"""Intelligence loop helpers — utility functions used across stages."""
from __future__ import annotations

import time
from typing import Any

from utils.helpers import safe_float, safe_int


def _ab_test_decision(options: list[dict], goal: str) -> dict[str, Any] | None:
    """Occasionally A/B test the second-best option against the best.

    Returns None (use best) or a dict with the selected variant.
    Uses ABFramework if available, falls back to simple random.
    """
    if len(options) < 2:
        return None
    try:
        from core.intelligence.ab_framework import ABFramework
        ab = ABFramework()

        exp_name = f"decision_{goal}"

        # Check if experiment exists, create if not
        existing = [e for e in ab._experiments.values() if e.get("name") == exp_name and e.get("status") == "running"]
        if existing:
            exp = existing[0]
        else:
            exp = ab.create_experiment(
                name=exp_name,
                test_type="decision_strategy",
                variants=[
                    {"name": "best_score", "strategy": "highest_score"},
                    {"name": "second_best", "strategy": "explore_alternative"},
                ],
                traffic_pct=100,
                min_samples=20,
            )

        # Assign variant based on timestamp (deterministic per cycle)
        assignment = ab.assign_variant(exp["id"], str(int(time.time())))

        if assignment.get("assigned") and assignment.get("variant_index") == 1:
            # A/B test: use second-best option
            ab.record_impression(exp["id"], 1)
            return {
                "selected": options[1],
                "variant_name": "explore_alternative",
                "experiment_id": exp["id"],
            }
        else:
            ab.record_impression(exp["id"], 0)
            return None  # Use best (default)

    except Exception:
        return None


def _get_past_learning(goal: str) -> dict[str, Any]:
    try:
        from core.learning.outcome_tracker import OutcomeTracker
        patterns = OutcomeTracker().get_winning_patterns("intelligence_loop")
        result: dict[str, Any] = {"success_rate": patterns.get("success_rate", 0)}
        for p in patterns.get("patterns", []):
            if p.get("pattern") == "avoid_low_scores":
                result["avoid_below_score"] = safe_float(p.get("threshold"))
            if p.get("pattern") == "quality_matters":
                result["min_quality"] = 50
        return result
    except Exception:
        return {}


def _calc_opportunity(analysis: dict) -> int:
    score = 50
    products = analysis.get("products", {})
    if products.get("viable", 0) > 0:
        score += 20
    if safe_float(products.get("avg_score")) > 7:
        score += 10
    customers = analysis.get("customers", {})
    if safe_float(customers.get("repeat_rate")) > 30:
        score += 10
    if safe_int(customers.get("at_risk")) > 0:
        score -= 5
    revenue = analysis.get("revenue", {})
    if safe_float(revenue.get("aov")) > 50:
        score += 10
    return max(0, min(100, score))


def summarize(decision, plan, execution, learning, elapsed) -> str:
    lines = [
        f"Decision: {decision['recommended_action'][:80]}",
        f"Confidence: {decision['confidence']} ({decision['confidence_score']}/100)",
        f"Options: {decision.get('options_evaluated', 1)} evaluated",
        f"Actions: {plan['total']} planned, {len(execution['ready'])} ready",
    ]
    if learning.get("past_outcomes", 0) > 0:
        lines.append(f"Learning: {learning['past_outcomes']} past outcomes, success {learning.get('success_rate', 0):.0%}")
    lines.append(f"Time: {elapsed:.3f}s")
    return "\n".join(lines)

# Alias
_summarize = summarize


def abort(loop_id, reason, clean_result, start_time):
    elapsed = time.monotonic() - start_time
    return {
        "loop_id": loop_id, "status": "aborted", "reason": reason,
        "data_quality": clean_result["quality_score"],
        "data_issues": clean_result["issues"],
        "elapsed_seconds": round(elapsed, 3),
        "stages_completed": 1,
        "summary": f"ABORTED: {reason}. Fix data quality first.",
    }

# Alias
_abort = abort


def get_history(history: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    return list(history[-limit:])
