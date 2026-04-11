"""Quality Control Layer — validates all system output.

Quality Layer зөвхөн ШАЛГАНА. Execution хийхгүй. Decision хийхгүй.

Шалгах:
  1. Output quality — хэрэгтэй юу?
  2. Decision quality — логиктой юу?
  3. Execution validity — бодит болсон уу?
  4. Profit impact — ашигтай юу?
  5. Failure detection — алдаа байна уу?
  6. Intelligence scoring — ухаантай ажилласан уу?
"""
from __future__ import annotations

import time
from typing import Any


class QualityChecker:
    """Validates all engine/agent output before it leaves the system."""

    def check(self, output: dict[str, Any], source: str = "unknown") -> dict[str, Any]:
        """Run all quality checks on an output.

        Args:
            output: Engine or agent output following contract
            source: Who produced this (engine name or agent name)

        Returns:
            {status, data: {quality_score, decision_score, issues, suggestions}, meta, error}
        """
        checks = {}

        # 1. Output structure quality
        checks["output_quality"] = self._check_output_quality(output)

        # 2. Decision quality
        checks["decision_quality"] = self._check_decision_quality(output)

        # 3. Execution validity
        checks["execution_valid"] = self._check_execution(output)

        # 4. Data completeness
        checks["data_completeness"] = self._check_data_completeness(output)

        # 5. Confidence calibration
        checks["confidence_calibration"] = self._check_confidence(output)

        # 6. Actionability
        checks["actionability"] = self._check_actionability(output)

        # Aggregate scores
        scores = [v.get("score", 0) for v in checks.values()]
        quality_score = round(sum(scores) / max(len(scores), 1))
        issues = []
        suggestions = []
        for name, check in checks.items():
            issues.extend(check.get("issues", []))
            suggestions.extend(check.get("suggestions", []))

        return {
            "status": "success",
            "data": {
                "quality_score": quality_score,
                "quality_grade": _grade(quality_score),
                "checks": checks,
                "issues": issues,
                "improvement_suggestions": suggestions,
                "source": source,
            },
            "meta": {
                "layer": "quality_control",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "error": None,
        }

    def _check_output_quality(self, output: dict[str, Any]) -> dict[str, Any]:
        """Does output follow contract? Is data useful?"""
        score = 0
        issues = []

        # Contract fields
        for field in ("status", "data", "meta", "error"):
            if field in output:
                score += 10
            else:
                issues.append(f"Missing contract field: {field}")

        # Status valid
        if output.get("status") in ("success", "fail"):
            score += 10
        else:
            issues.append(f"Invalid status: {output.get('status')}")

        # Data not empty
        data = output.get("data")
        if isinstance(data, dict) and data:
            score += 20
            if len(data) > 3:
                score += 10  # Rich data
        elif data is not None:
            score += 5
            issues.append("Data is minimal")
        else:
            issues.append("Data is None")

        # Meta has useful info
        meta = output.get("meta", {})
        if meta.get("engine") or meta.get("agent"):
            score += 10
        if meta.get("confidence") is not None:
            score += 10
        if meta.get("timestamp"):
            score += 10

        return {"score": min(100, score), "issues": issues, "suggestions": []}

    def _check_decision_quality(self, output: dict[str, Any]) -> dict[str, Any]:
        """Is the decision logical and data-based?"""
        score = 50  # Base — no decision info available
        issues = []
        suggestions = []

        data = output.get("data", {})
        if not isinstance(data, dict):
            return {"score": 30, "issues": ["Cannot assess decision quality — no data"], "suggestions": []}

        # Has recommendation?
        has_rec = data.get("recommendation") or data.get("verdict") or data.get("action")
        if has_rec:
            score += 20
        else:
            issues.append("No clear recommendation in output")
            suggestions.append("Add recommendation or verdict to output")

        # Has reasoning?
        has_reason = data.get("reason") or data.get("reasons") or data.get("summary")
        if has_reason:
            score += 15
        else:
            issues.append("Decision has no reasoning")
            suggestions.append("Add reasoning to explain why this decision was made")

        # Has alternatives?
        has_alts = data.get("alternatives") or data.get("other_options")
        if has_alts:
            score += 15
        else:
            suggestions.append("Include alternative options that were considered")

        return {"score": min(100, score), "issues": issues, "suggestions": suggestions}

    def _check_execution(self, output: dict[str, Any]) -> dict[str, Any]:
        """Was the execution real? Not fake?"""
        score = 50
        issues = []

        if output.get("status") == "success":
            score += 30
        elif output.get("status") == "fail":
            error = output.get("error", {})
            if isinstance(error, dict) and error.get("reason"):
                score += 15  # At least we know why it failed
                issues.append(f"Execution failed: {error['reason']}")
            else:
                issues.append("Execution failed without explanation")

        # Check for mock/fake indicators
        meta = output.get("meta", {})
        if meta.get("mock") or meta.get("simulated"):
            score -= 20
            issues.append("Output is mock/simulated — not real execution")

        return {"score": max(0, min(100, score)), "issues": issues, "suggestions": []}

    def _check_data_completeness(self, output: dict[str, Any]) -> dict[str, Any]:
        """How complete is the data?"""
        data = output.get("data", {})
        if not isinstance(data, dict):
            return {"score": 0, "issues": ["No data"], "suggestions": []}

        total_fields = len(data)
        non_empty = sum(1 for v in data.values() if v is not None and v != "" and v != [] and v != {})

        if total_fields == 0:
            return {"score": 0, "issues": ["Data is empty"], "suggestions": []}

        completeness = non_empty / total_fields
        score = round(completeness * 100)

        issues = []
        if completeness < 0.5:
            issues.append(f"Only {non_empty}/{total_fields} data fields populated")

        return {"score": score, "issues": issues, "suggestions": []}

    def _check_confidence(self, output: dict[str, Any]) -> dict[str, Any]:
        """Is confidence score reasonable?"""
        meta = output.get("meta", {})
        confidence = meta.get("confidence")

        if confidence is None:
            return {"score": 40, "issues": ["No confidence score provided"], "suggestions": ["Add confidence to meta"]}

        if not (0 <= confidence <= 1):
            return {"score": 20, "issues": [f"Confidence {confidence} out of 0-1 range"], "suggestions": []}

        # Suspicious patterns
        issues = []
        if confidence == 1.0:
            issues.append("Confidence = 1.0 (perfect) — suspiciously high")
            return {"score": 50, "issues": issues, "suggestions": ["Confidence should rarely be 1.0"]}
        if confidence == 0:
            issues.append("Confidence = 0 — no confidence at all")
            return {"score": 30, "issues": issues, "suggestions": []}

        return {"score": 80, "issues": [], "suggestions": []}

    def _check_actionability(self, output: dict[str, Any]) -> dict[str, Any]:
        """Can someone ACT on this output?"""
        data = output.get("data", {})
        if not isinstance(data, dict):
            return {"score": 0, "issues": ["No data to act on"], "suggestions": []}

        score = 0
        suggestions = []

        # Has clear next steps?
        if data.get("next_steps") or data.get("action") or data.get("recommended_action"):
            score += 40
        else:
            suggestions.append("Add clear next_steps or recommended_action")

        # Has specific data to base decisions on?
        has_numbers = any(isinstance(v, (int, float)) for v in data.values())
        if has_numbers:
            score += 20

        # Has categories/segmentation?
        if data.get("category") or data.get("segments") or data.get("gaps"):
            score += 20

        # Has timeline?
        if data.get("timeline") or data.get("launch_window") or data.get("when"):
            score += 20
        else:
            suggestions.append("Add timeline or timing recommendation")

        return {"score": min(100, score), "issues": [], "suggestions": suggestions}


def _grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    if score >= 35:
        return "D"
    return "F"
