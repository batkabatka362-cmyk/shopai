"""Evaluator — evaluates engine output quality."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("testing.evaluator")


class Evaluator:
    def evaluate(self, output: dict[str, Any], criteria: dict[str, Any] | None = None) -> dict[str, Any]:
        score = 0.0
        checks = []
        if output.get("status") == "completed":
            score += 0.5
            checks.append("status_ok")
        if output.get("result"):
            score += 0.3
            checks.append("has_result")
        if output.get("steps"):
            score += 0.2
            checks.append("has_steps")
        return {"score": score, "checks": checks, "passed": score >= 0.5}
