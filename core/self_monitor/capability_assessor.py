"""CapabilityAssessor — does the system know its own limits?

"Би 70% confidence гэж хэлэхэд бодитоор 45% амжилттай"
→ System miscalibrated → escalate big decisions to human.

Tracks actual success rate per decision type, compares to claimed
confidence, and flags overconfidence.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("self_monitor.capability")


class CapabilityAssessor:
    """Tracks system capability per decision type and flags overconfidence.

    Usage:
        assessor = CapabilityAssessor(episodic_memory)
        result = assessor.assess("pricing", claimed_confidence=75)
        # result = {
        #   "capable": True/False,
        #   "actual_success_rate": 45.0,
        #   "calibration_gap": 30,
        #   "recommendation": "Lower confidence or escalate to human",
        # }
    """

    def __init__(self, episodic_memory: Any = None) -> None:
        self._memory = episodic_memory

    def assess(
        self,
        decision_type: str,
        claimed_confidence: int = 50,
    ) -> dict[str, Any]:
        """Assess system capability for a decision type.

        Args:
            decision_type: Type of decision (pricing, launch, marketing, etc.)
            claimed_confidence: What the system claims (0-100)

        Returns:
            Capability assessment with calibration check.
        """
        profile = self._get_capability_profile(decision_type)

        actual_rate = profile["success_rate"]
        sample_size = profile["sample_size"]

        # Calibration: compare claimed vs actual
        calibration_gap = claimed_confidence - actual_rate if sample_size >= 3 else 0
        miscalibrated = calibration_gap > 20 and sample_size >= 5

        # Capability score: weighted combination of success rate + sample confidence
        sample_confidence = min(100, sample_size * 10)  # More samples = more confident in the rate
        capability_score = round(
            actual_rate * 0.7 + sample_confidence * 0.3
            if sample_size >= 3 else claimed_confidence * 0.5,
            1,
        )

        # Should escalate?
        should_escalate = (
            (miscalibrated and claimed_confidence > 60)
            or (actual_rate < 40 and sample_size >= 5)
            or (capability_score < 30)
        )

        recommendation = self._recommend(
            miscalibrated, actual_rate, sample_size, claimed_confidence, capability_score,
        )

        return {
            "decision_type": decision_type,
            "claimed_confidence": claimed_confidence,
            "actual_success_rate": actual_rate,
            "sample_size": sample_size,
            "calibration_gap": round(calibration_gap, 1),
            "miscalibrated": miscalibrated,
            "capability_score": capability_score,
            "should_escalate": should_escalate,
            "recommendation": recommendation,
            "profile": profile,
        }

    def get_full_profile(self) -> dict[str, Any]:
        """Get capability profile across all decision types."""
        if self._memory is None:
            return {"status": "no_memory"}

        stats = self._memory.get_stats()
        by_type = stats.get("by_type", {})

        profiles = {}
        for dt in by_type:
            profiles[dt] = self._get_capability_profile(dt)

        overall = self._memory.get_success_rate()

        return {
            "overall_success_rate": overall.get("success_rate", 0),
            "total_decisions": overall.get("total", 0),
            "by_type": profiles,
            "strongest": max(profiles.items(), key=lambda x: x[1]["success_rate"])[0] if profiles else None,
            "weakest": min(profiles.items(), key=lambda x: x[1]["success_rate"])[0] if profiles else None,
        }

    def _get_capability_profile(self, decision_type: str) -> dict[str, Any]:
        """Build capability profile for a decision type from episodic memory."""
        if self._memory is None:
            return {"success_rate": 50, "sample_size": 0, "status": "no_data"}

        rate_data = self._memory.get_success_rate(decision_type)
        total = rate_data.get("total", 0)
        successes = rate_data.get("successes", 0)
        failures = rate_data.get("failures", 0)
        success_rate = rate_data.get("success_rate", 50)

        # Get recent trend (last 5 episodes)
        lessons = self._memory.get_lessons(decision_type, limit=5)
        recent_success = sum(1 for l in lessons if l.get("success", False))
        recent_total = len(lessons)
        trend = "improving" if recent_total >= 3 and recent_success / recent_total > success_rate / 100 else "stable"
        if recent_total >= 3 and recent_success / recent_total < (success_rate / 100) * 0.7:
            trend = "declining"

        return {
            "success_rate": success_rate,
            "sample_size": total,
            "successes": successes,
            "failures": failures,
            "trend": trend,
            "status": "sufficient_data" if total >= 5 else "limited_data" if total > 0 else "no_data",
        }

    def _recommend(
        self,
        miscalibrated: bool,
        actual_rate: float,
        sample_size: int,
        claimed: int,
        capability: float,
    ) -> str:
        """Generate recommendation based on assessment."""
        if sample_size < 3:
            return "Insufficient data — proceed with caution, collect more outcomes"

        if miscalibrated:
            return (
                f"OVERCONFIDENT: System claims {claimed}% but actual is {actual_rate:.0f}%. "
                f"Reduce risk on {claimed - actual_rate:.0f}% of decisions or escalate to human."
            )

        if actual_rate < 40:
            return (
                f"LOW CAPABILITY: Only {actual_rate:.0f}% success rate. "
                "Recommend human review for all decisions of this type."
            )

        if capability > 70:
            return f"Good capability ({capability:.0f}/100) — proceed normally"

        return f"Moderate capability ({capability:.0f}/100) — proceed but monitor closely"
