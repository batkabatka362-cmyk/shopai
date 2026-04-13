"""Autonomous Decision Engine — decision selector.

Select the best option based on predicted outcomes, feasibility,
and goal alignment. Produces final decision with alternatives.
"""
from __future__ import annotations

import copy
from typing import Any


def select_decision(
    **kwargs: Any,
) -> dict[str, Any]:
    """Select the best decision option.

    Args:
        **kwargs: Must include outcome_predictor_data with predictions.

    Returns:
        Structured dict with selected decision, alternatives, confidence.
    """
    try:
        pred_data = kwargs.get("outcome_predictor_data", {})
        predictions = copy.deepcopy(pred_data.get("predictions", []))
        gen_data = kwargs.get("option_generator_data", {})
        options = copy.deepcopy(gen_data.get("options", []))
        goal = str(kwargs.get("goal", ""))

        opt_map = {str(o.get("id", "")): o for o in options}

        # Score each prediction: combine success probability and risk
        scored: list[dict[str, Any]] = []
        for pred in predictions:
            oid = pred.get("option_id", "unknown")
            success = float(pred.get("predicted_success", 0))
            risk_map = {"low": 1.0, "medium": 0.7, "high": 0.3}
            risk_factor = risk_map.get(pred.get("risk", "high"), 0.3)
            score = round(success * risk_factor, 3)
            scored.append({
                "option_id": oid,
                "score": score,
                "prediction": pred,
                "option": opt_map.get(oid, {}),
            })

        scored.sort(key=lambda s: s["score"], reverse=True)

        if not scored:
            return {
                "status": "success",
                "result": {
                    "decision": None,
                    "alternatives": [],
                    "predicted_outcome": {},
                    "confidence": 0.0,
                    "reasoning": "No viable options available",
                },
            }

        best = scored[0]
        alternatives = scored[1:4]  # Top 3 alternatives

        confidence = round(best["score"], 2)
        reasoning = (
            f"Selected option '{best['option_id']}' with score {best['score']} "
            f"(success: {best['prediction'].get('predicted_success')}, "
            f"risk: {best['prediction'].get('risk')}). "
            f"Goal: {goal}"
        )

        return {
            "status": "success",
            "result": {
                "decision": best["option"],
                "alternatives": [a["option"] for a in alternatives],
                "predicted_outcome": best["prediction"],
                "confidence": confidence,
                "reasoning": reasoning,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Decision selection failed: {exc}"}
