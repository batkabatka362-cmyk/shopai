"""LearningEngine — analyzes feedback and produces improvement recommendations.

Cycle: Collect feedback → Analyze patterns → Generate recommendations → Apply
This is the brain of the self-learning loop.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .feedback_store import FeedbackStore

logger = get_logger("learning.engine")


class LearningEngine:
    """Learns from engine execution history and recommends improvements."""

    def __init__(self, feedback_store: FeedbackStore | None = None) -> None:
        self._feedback = feedback_store or FeedbackStore()

    def analyze(self, engine_name: str) -> dict[str, Any]:
        """Analyze an engine's performance and return insights."""
        stats = self._feedback.get_stats(engine_name)
        history = self._feedback.get_history(engine_name, limit=500)

        insights = {
            "engine": engine_name,
            "stats": stats,
            "patterns": self._detect_patterns(history),
            "recommendations": self._generate_recommendations(stats, history),
            "risk_level": self._assess_risk(stats),
        }
        logger.info("Analysis complete for %s: risk=%s, recs=%d",
                     engine_name, insights["risk_level"], len(insights["recommendations"]))
        return insights

    def analyze_system(self) -> dict[str, Any]:
        """Analyze the entire system's learning state."""
        all_stats = self._feedback.get_all_stats()
        if not all_stats:
            return {"status": "no_data", "engines_analyzed": 0, "recommendations": []}

        # Find worst performers
        worst = sorted(
            [(n, s) for n, s in all_stats.items() if s["total_runs"] > 0],
            key=lambda x: x[1].get("success_rate", 1),
        )[:10]

        # Find slowest engines
        slowest = sorted(
            [(n, s) for n, s in all_stats.items() if s.get("avg_elapsed", 0) > 0],
            key=lambda x: x[1]["avg_elapsed"],
            reverse=True,
        )[:10]

        # Find declining engines
        declining = [(n, s) for n, s in all_stats.items() if s.get("trend") == "declining"]

        system_recs = []
        for name, stat in worst[:3]:
            if stat["success_rate"] < 0.8:
                system_recs.append({
                    "type": "fix_reliability",
                    "engine": name,
                    "success_rate": stat["success_rate"],
                    "action": f"Engine {name} has {stat['success_rate']:.0%} success rate — investigate common errors",
                })

        for name, stat in declining:
            system_recs.append({
                "type": "investigate_decline",
                "engine": name,
                "trend": "declining",
                "action": f"Engine {name} performance is declining — review recent changes",
            })

        return {
            "status": "analyzed",
            "engines_analyzed": len(all_stats),
            "total_runs": sum(s["total_runs"] for s in all_stats.values()),
            "system_success_rate": self._system_success_rate(all_stats),
            "worst_performers": [(n, s["success_rate"]) for n, s in worst[:5]],
            "slowest_engines": [(n, s["avg_elapsed"]) for n, s in slowest[:5]],
            "declining_engines": [n for n, _ in declining],
            "recommendations": system_recs,
        }

    def _detect_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect recurring patterns in engine execution history."""
        patterns = []
        if not history:
            return patterns

        # Pattern: specific steps always fail
        step_failures: dict[str, int] = {}
        for h in history:
            for step in h.get("failed_steps", []):
                step_failures[step] = step_failures.get(step, 0) + 1
        for step, count in step_failures.items():
            if count >= 3:
                patterns.append({
                    "type": "recurring_step_failure",
                    "step": step,
                    "count": count,
                    "severity": "high" if count > 10 else "medium",
                })

        # Pattern: performance degradation over time
        if len(history) >= 20:
            recent = history[-10:]
            older = history[-20:-10]
            recent_avg = sum(h["elapsed_seconds"] for h in recent) / 10
            older_avg = sum(h["elapsed_seconds"] for h in older) / 10
            if recent_avg > older_avg * 1.5:
                patterns.append({
                    "type": "performance_degradation",
                    "recent_avg_ms": round(recent_avg * 1000),
                    "older_avg_ms": round(older_avg * 1000),
                    "severity": "medium",
                })

        # Pattern: burst failures (multiple failures in short window)
        failure_times = [h["timestamp"] for h in history if h["status"] == "failed"]
        for i in range(len(failure_times) - 2):
            window = failure_times[i + 2] - failure_times[i]
            if window < 60:  # 3 failures in 60 seconds
                patterns.append({
                    "type": "burst_failure",
                    "window_seconds": round(window),
                    "severity": "high",
                })
                break

        return patterns

    def _generate_recommendations(self, stats: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate actionable recommendations based on analysis."""
        recs = []

        if stats["total_runs"] == 0:
            return [{"type": "no_data", "action": "Run engine at least once to generate learning data"}]

        # Low success rate
        if stats["success_rate"] < 0.9:
            errors = stats.get("common_errors", [])
            recs.append({
                "type": "improve_reliability",
                "priority": "high",
                "success_rate": stats["success_rate"],
                "action": f"Fix top errors: {errors[:2]}" if errors else "Investigate failure causes",
            })

        # Slow execution
        if stats.get("avg_elapsed", 0) > 5.0:
            recs.append({
                "type": "optimize_speed",
                "priority": "medium",
                "avg_elapsed": stats["avg_elapsed"],
                "action": "Profile slow steps and optimize model calls",
            })

        # Low quality scores
        if stats.get("avg_quality") is not None and stats["avg_quality"] < 7.0:
            recs.append({
                "type": "improve_quality",
                "priority": "medium",
                "avg_quality": stats["avg_quality"],
                "action": "Review and improve prompts for better output quality",
            })

        # Declining trend
        if stats.get("trend") == "declining":
            recs.append({
                "type": "investigate_decline",
                "priority": "high",
                "action": "Recent performance is worse than historical — investigate",
            })

        if not recs:
            recs.append({"type": "healthy", "priority": "low", "action": "Engine performing well — no action needed"})

        return recs

    def _assess_risk(self, stats: dict[str, Any]) -> str:
        """Assess overall risk level for an engine."""
        if stats["total_runs"] == 0:
            return "unknown"
        if stats["success_rate"] < 0.7:
            return "critical"
        if stats["success_rate"] < 0.9:
            return "warning"
        if stats.get("trend") == "declining":
            return "watch"
        return "healthy"

    @staticmethod
    def _system_success_rate(all_stats: dict[str, dict[str, Any]]) -> float:
        total_runs = sum(s["total_runs"] for s in all_stats.values())
        total_completed = sum(s["completed"] for s in all_stats.values())
        return round(total_completed / total_runs, 4) if total_runs else 0
