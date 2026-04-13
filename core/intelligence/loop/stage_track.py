"""Stage 6: TRACK — record decisions for outcome learning."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.loop.track")


def stage_track(loop_id: str, context: dict[str, Any]) -> None:
    """Record the decision in OutcomeTracker for future learning."""
    try:
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        decision = context.get("decision", {})
        analysis = context.get("analysis", {})
        ot.record_decision(loop_id, "intelligence_loop", {
            "goal": context.get("goal"),
            "action": decision.get("recommended_action", ""),
            "confidence": decision.get("confidence", ""),
            "confidence_score": decision.get("confidence_score", 0),
            "opportunity_score": decision.get("opportunity_score", 0),
            "data_quality": context.get("clean", {}).get("quality_score", 0),
            "viable_products": analysis.get("products", {}).get("viable", 0),
            "avg_score": analysis.get("products", {}).get("avg_score", 0),
            "decision_type": decision.get("decision_type", ""),
            "options_evaluated": decision.get("options_evaluated", 0),
        })
    except Exception as exc:
        logger.debug("outcome tracking failed: %s", exc)
