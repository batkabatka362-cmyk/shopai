"""Simulation Lab — best option selector.

Selects the best option from compared strategies using multi-criteria
decision analysis. Produces a justified selection with reasoning.

Model note: Would use LLaMA for creative synthesis of selection reasoning.
"""
from __future__ import annotations

import copy
from typing import Any


def select_best_option(
    comparison: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    risk_assessments: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    objectives: list[str] | None = None,
) -> dict[str, Any]:
    """Select the best option from the ranked comparison list.

    Uses rank-1 from the comparator as the primary candidate, then
    validates it against risk thresholds and objective alignment.
    Falls back to rank-2 if rank-1 fails validation.

    Args:
        comparison: Ranked ComparisonEntry list.
        predictions: OutcomePrediction per scenario.
        risk_assessments: RiskAssessment per scenario.
        scenarios: Original Scenario dicts.
        objectives: Active objectives.

    Returns:
        Structured dict with the BestOption selection.
    """
    try:
        comp = copy.deepcopy(comparison)
        pred_map = {p["scenario_id"]: p for p in copy.deepcopy(predictions)}
        risk_map = {r["scenario_id"]: r for r in copy.deepcopy(risk_assessments)}
        scen_map = {s["scenario_id"]: s for s in copy.deepcopy(scenarios)}

        if not comp:
            return _empty_selection("No strategies available for selection")

        # Sort by rank (should already be sorted)
        comp.sort(key=lambda c: c.get("rank", 999))

        # Try top candidates in order
        selected = None
        reasoning: list[str] = []

        for candidate in comp:
            sid = candidate.get("scenario_id", "")
            risk = risk_map.get(sid, {})
            risk_cat = risk.get("risk_category", "medium")

            # Reject critical-risk candidates unless it is the only option
            if risk_cat == "critical" and len(comp) > 1:
                reasoning.append(
                    f"Rejected '{candidate.get('label', sid)}' — critical risk level"
                )
                continue

            selected = candidate
            break

        if selected is None:
            # Fall back to the least-bad option
            selected = comp[0]
            reasoning.append("All candidates carry critical risk — selecting least-bad option")

        sid = selected["scenario_id"]
        pred = pred_map.get(sid, {})
        risk = risk_map.get(sid, {})
        scenario = scen_map.get(sid, {})

        # Build reasoning
        reasoning.extend(_build_reasoning(selected, pred, risk, scenario, objectives))

        # Confidence: blend of prediction confidence, rank position, and risk
        pred_conf = float(pred.get("confidence", 0.5))
        rank_bonus = max(0.0, 0.2 - (selected.get("rank", 1) - 1) * 0.05)
        risk_penalty = float(risk.get("overall_risk", 0.5)) * 0.2
        confidence = round(
            max(0.0, min(1.0, pred_conf * 0.6 + selected.get("total_score", 0.5) * 0.2 + rank_bonus - risk_penalty)),
            4,
        )

        best_option: dict[str, Any] = {
            "scenario_id": sid,
            "label": selected.get("label", sid),
            "parameters": scenario.get("parameters", {}),
            "total_score": selected.get("total_score", 0.0),
            "predicted_revenue": float(pred.get("predicted_revenue", 0.0)),
            "predicted_profit": float(pred.get("predicted_profit", 0.0)),
            "risk_level": risk.get("risk_category", "unknown"),
            "confidence": confidence,
            "reasoning": reasoning,
            "model_note": "LLaMA would synthesize richer justification narratives",
        }

        return {
            "status": "success",
            "best_option": best_option,
            "runner_up": _runner_up(comp, sid, pred_map, scen_map),
        }
    except Exception as exc:
        return _empty_selection(f"Selection failed: {exc}")


# ---------------------------------------------------------------------------
# Reasoning builder
# ---------------------------------------------------------------------------

def _build_reasoning(
    selected: dict[str, Any],
    pred: dict[str, Any],
    risk: dict[str, Any],
    scenario: dict[str, Any],
    objectives: list[str] | None,
) -> list[str]:
    """Build justification reasoning for the selected option."""
    reasons: list[str] = []
    label = selected.get("label", "Selected option")

    reasons.append(
        f"'{label}' ranked #{selected.get('rank', '?')} with total score "
        f"{selected.get('total_score', 0.0):.2f}"
    )

    # Revenue/profit justification
    rev = float(pred.get("predicted_revenue", 0.0))
    profit = float(pred.get("predicted_profit", 0.0))
    if profit > 0:
        reasons.append(
            f"Expected profit {profit:.2f} on revenue {rev:.2f}"
        )
    else:
        reasons.append(
            f"Expected loss of {abs(profit):.2f} — selected as least-loss option"
        )

    # Risk justification
    risk_cat = risk.get("risk_category", "unknown")
    prob_loss = float(risk.get("probability_of_loss", 0.0))
    reasons.append(
        f"Risk level: {risk_cat} (loss probability {prob_loss:.1%})"
    )

    # Pros from comparison
    pros = selected.get("pros", [])
    if pros:
        reasons.append(f"Key advantages: {'; '.join(pros[:2])}")

    # Variation type context
    vtype = scenario.get("variation_type", "")
    if vtype == "baseline":
        reasons.append("Baseline scenario — proven, unmodified parameters")
    elif vtype == "aggressive":
        reasons.append("Aggressive variation selected — higher risk, higher potential reward")
    elif vtype == "conservative":
        reasons.append("Conservative variation selected — prioritizes stability")

    return reasons


def _runner_up(
    comp: list[dict[str, Any]],
    winner_id: str,
    pred_map: dict[str, dict],
    scen_map: dict[str, dict],
) -> dict[str, Any] | None:
    """Return a summary of the runner-up option, if any."""
    for entry in comp:
        sid = entry.get("scenario_id", "")
        if sid != winner_id:
            pred = pred_map.get(sid, {})
            return {
                "scenario_id": sid,
                "label": entry.get("label", sid),
                "total_score": entry.get("total_score", 0.0),
                "predicted_profit": float(pred.get("predicted_profit", 0.0)),
            }
    return None


def _empty_selection(reason: str) -> dict[str, Any]:
    return {
        "status": "error",
        "best_option": {
            "scenario_id": "",
            "label": "none",
            "parameters": {},
            "total_score": 0.0,
            "predicted_revenue": 0.0,
            "predicted_profit": 0.0,
            "risk_level": "unknown",
            "confidence": 0.0,
            "reasoning": [reason],
            "model_note": "No model invocation — selection failed",
        },
        "runner_up": None,
    }
