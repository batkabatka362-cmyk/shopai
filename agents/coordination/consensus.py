"""Consensus — reach consensus between agents."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("agents.consensus")


class Consensus:
    def reach(self, votes: list[dict[str, Any]]) -> dict[str, Any]:
        if not votes:
            return {"consensus": None, "confidence": 0}
        scores = {}
        for vote in votes:
            choice = vote.get("choice", "")
            scores[choice] = scores.get(choice, 0) + vote.get("weight", 1)
        winner = max(scores, key=scores.get)
        total = sum(scores.values())
        confidence = scores[winner] / total if total > 0 else 0
        logger.info("Consensus: %s (confidence=%.2f)", winner, confidence)
        return {"consensus": winner, "confidence": confidence, "scores": scores}
