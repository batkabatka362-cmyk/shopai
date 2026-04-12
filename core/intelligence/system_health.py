"""SystemHealthReport — monitors overall ShopAI system health.

Answers: Is the system improving? Where are the bottlenecks?

Sections:
  - Decision quality: accuracy, confidence calibration
  - Execution health: success rate, retry rate, latency
  - Learning progress: patterns found, weights changed
  - Data quality: trend, common issues
  - Revenue impact: ROI per decision type
"""
from __future__ import annotations

import time
from typing import Any

# ── Health grade thresholds ──────────────────────────────────
GRADE_A_THRESHOLD = 0.9       # success rate above this → grade A
GRADE_B_THRESHOLD = 0.7       # success rate above this → grade B
GRADE_C_THRESHOLD = 0.5       # success rate above this → grade C
EXECUTION_CONCERN_THRESHOLD = 0.7  # below this → flag as issue

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.health")


class SystemHealthReport:
    """Generates comprehensive system health report."""

    def generate(self) -> dict[str, Any]:
        """Generate full system health report."""
        start = time.monotonic()

        report = {
            "generated_at": time.time(),
            "sections": {},
        }

        # 1. Decision quality
        report["sections"]["decision_quality"] = self._decision_quality()

        # 2. Execution health
        report["sections"]["execution_health"] = self._execution_health()

        # 3. Learning progress
        report["sections"]["learning_progress"] = self._learning_progress()

        # 4. Data quality
        report["sections"]["data_quality"] = self._data_quality()

        # 5. Revenue impact
        report["sections"]["revenue_impact"] = self._revenue_impact()

        # Overall system grade
        report["overall_grade"] = self._calculate_grade(report["sections"])
        report["generation_time_ms"] = round((time.monotonic() - start) * 1000, 1)

        return report

    def _decision_quality(self) -> dict[str, Any]:
        """Assess decision-making quality."""
        try:
            from core.intelligence.kpi_tracker import KPITracker
            kpis = KPITracker().get_decision_kpis()
            if kpis.get("status") == "no_data":
                return {"status": "no_data", "grade": "N/A"}

            success_rate = kpis.get("overall_success_rate", 0)
            calibrated = kpis.get("confidence_calibrated")

            grade = "A" if success_rate > 70 else "B" if success_rate > 50 else "C" if success_rate > 30 else "F"
            issues = []
            if success_rate < 50:
                issues.append("Decision success rate below 50%")
            if calibrated is False:
                issues.append("Confidence scores not calibrated — high confidence doesn't predict success")

            return {
                "grade": grade,
                "success_rate": success_rate,
                "confidence_calibrated": calibrated,
                "by_confidence": kpis.get("by_confidence", {}),
                "by_decision_type": kpis.get("by_decision_type", {}),
                "issues": issues,
            }
        except Exception:
            return {"status": "unavailable", "grade": "N/A"}

    def _execution_health(self) -> dict[str, Any]:
        """Assess execution pipeline health."""
        try:
            from core.bridge.execution_bridge import ExecutionBridge
            eb = ExecutionBridge()
            stats = eb.get_execution_stats()
            if stats.get("total", 0) == 0:
                return {"status": "no_data", "grade": "N/A"}

            rate = stats.get("success_rate", 0)
            grade = "A" if rate > GRADE_A_THRESHOLD else "B" if rate > GRADE_B_THRESHOLD else "C" if rate > GRADE_C_THRESHOLD else "F"

            issues = []
            if rate < EXECUTION_CONCERN_THRESHOLD:
                issues.append(f"Execution success rate {rate:.0%} — check failing executors")

            return {
                "grade": grade,
                "total_executed": stats["total"],
                "success_rate": rate,
                "avg_duration_ms": stats.get("avg_duration_ms", 0),
                "by_action_type": stats.get("by_action_type", {}),
                "issues": issues,
            }
        except Exception:
            return {"status": "unavailable", "grade": "N/A"}

    def _learning_progress(self) -> dict[str, Any]:
        """Assess how well the learning system is working."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            from core.intelligence_loop import get_learned_weights

            ot = OutcomeTracker()
            patterns = ot.get_winning_patterns("intelligence_loop")
            fsl_patterns = ot.get_winning_patterns("full_system_loop")

            weights = get_learned_weights()
            pattern_count = len(patterns.get("patterns", [])) + len(fsl_patterns.get("patterns", []))
            outcomes = patterns.get("with_outcomes", 0) + fsl_patterns.get("with_outcomes", 0)

            # Has learning actually produced weight changes?
            learning_active = len(weights) > 0

            grade = "A" if outcomes > 10 and learning_active else "B" if outcomes > 5 else "C" if outcomes > 0 else "F"

            confirmed = sum(1 for p in patterns.get("patterns", []) if p.get("correlation") == "confirmed")

            return {
                "grade": grade,
                "total_outcomes_tracked": outcomes,
                "patterns_discovered": pattern_count,
                "confirmed_patterns": confirmed,
                "weight_adjustments_active": weights,
                "learning_active": learning_active,
                "intelligence_loop_success_rate": patterns.get("success_rate", 0),
                "full_loop_success_rate": fsl_patterns.get("success_rate", 0),
            }
        except Exception:
            return {"status": "unavailable", "grade": "N/A"}

    def _data_quality(self) -> dict[str, Any]:
        """Assess data quality trends."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            entries = ot._load("intelligence_loop")
            fsl_entries = ot._load("full_system_loop")
            all_entries = entries + fsl_entries

            if not all_entries:
                return {"status": "no_data", "grade": "N/A"}

            qualities = [safe_float(e.get("decision", {}).get("data_quality")) for e in all_entries
                         if isinstance(e.get("decision"), dict)]
            qualities = [q for q in qualities if q > 0]

            if not qualities:
                return {"status": "no_data", "grade": "N/A"}

            avg_quality = sum(qualities) / len(qualities)
            recent = qualities[-10:] if len(qualities) > 10 else qualities
            recent_avg = sum(recent) / len(recent)

            trend = "improving" if recent_avg > avg_quality + 2 else "declining" if recent_avg < avg_quality - 2 else "stable"

            grade = "A" if avg_quality > 75 else "B" if avg_quality > 55 else "C" if avg_quality > 35 else "F"

            return {
                "grade": grade,
                "avg_quality": round(avg_quality, 1),
                "recent_avg": round(recent_avg, 1),
                "trend": trend,
                "samples": len(qualities),
            }
        except Exception:
            return {"status": "unavailable", "grade": "N/A"}

    def _revenue_impact(self) -> dict[str, Any]:
        """Assess revenue impact."""
        try:
            from core.intelligence.revenue_tracker import RevenueTracker
            rt = RevenueTracker()
            summary = rt.get_roi_summary()

            if summary.get("status") == "no_data":
                return {"status": "no_data", "grade": "N/A"}

            profit = safe_float(summary.get("total_profit"))
            roas = safe_float(summary.get("overall_roas"))

            grade = "A" if profit > 0 and roas > 3 else "B" if profit > 0 else "C" if roas > 1 else "F"

            return {
                "grade": grade,
                "total_revenue": summary.get("total_revenue", 0),
                "total_cost": summary.get("total_cost", 0),
                "total_profit": profit,
                "roas": roas,
                "by_action_type": summary.get("by_action_type", {}),
                "top_product": summary.get("top_product"),
            }
        except Exception:
            return {"status": "unavailable", "grade": "N/A"}

    @staticmethod
    def _calculate_grade(sections: dict[str, Any]) -> str:
        """Calculate overall system grade from section grades."""
        grade_values = {"A": 4, "B": 3, "C": 2, "F": 1, "N/A": 0}
        grades = []
        for section in sections.values():
            g = section.get("grade", "N/A")
            if g != "N/A":
                grades.append(grade_values.get(g, 0))

        if not grades:
            return "N/A"

        avg = sum(grades) / len(grades)
        if avg >= 3.5:
            return "A"
        if avg >= 2.5:
            return "B"
        if avg >= 1.5:
            return "C"
        return "F"
