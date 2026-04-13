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
        """Analyze the entire system's learning state.

        Every stats access uses `.get()` so a malformed entry from
        FeedbackStore.get_all_stats can't crash the whole system
        analysis with KeyError. Filter predicates also use .get()
        with safe defaults so missing fields are treated as zero
        rather than raising.
        """
        all_stats = self._feedback.get_all_stats()
        if not all_stats:
            return {"status": "no_data", "engines_analyzed": 0, "recommendations": []}

        # Filter to dict-shaped entries to defend against a future
        # FeedbackStore that returns the wrong shape.
        all_stats = {n: s for n, s in all_stats.items() if isinstance(s, dict)}

        # Find worst performers
        worst = sorted(
            [(n, s) for n, s in all_stats.items() if s.get("total_runs", 0) > 0],
            key=lambda x: x[1].get("success_rate", 1),
        )[:10]

        # Find slowest engines
        slowest = sorted(
            [(n, s) for n, s in all_stats.items() if s.get("avg_elapsed", 0) > 0],
            key=lambda x: x[1].get("avg_elapsed", 0),
            reverse=True,
        )[:10]

        # Find declining engines
        declining = [(n, s) for n, s in all_stats.items() if s.get("trend") == "declining"]

        system_recs = []
        for name, stat in worst[:3]:
            success_rate = stat.get("success_rate", 1)
            if success_rate < 0.8:
                system_recs.append({
                    "type": "fix_reliability",
                    "engine": name,
                    "success_rate": success_rate,
                    "action": f"Engine {name} has {success_rate:.0%} success rate — investigate common errors",
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
            "total_runs": sum(s.get("total_runs", 0) for s in all_stats.values()),
            "system_success_rate": self._system_success_rate(all_stats),
            "worst_performers": [(n, s.get("success_rate", 0)) for n, s in worst[:5]],
            "slowest_engines": [(n, s.get("avg_elapsed", 0)) for n, s in slowest[:5]],
            "declining_engines": [n for n, _ in declining],
            "recommendations": system_recs,
        }

    def _detect_patterns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect recurring patterns in engine execution history.

        Every entry access uses `.get()` + isinstance type checks
        so a malformed feedback row (missing status/timestamp/
        elapsed_seconds, or those fields stored as None) can't
        crash pattern detection with KeyError or TypeError.
        """
        patterns = []
        if not history:
            return patterns

        # Pattern: specific steps always fail
        step_failures: dict[str, int] = {}
        for h in history:
            for step in h.get("failed_steps") or []:
                step_failures[step] = step_failures.get(step, 0) + 1
        for step, count in step_failures.items():
            if count >= 3:
                patterns.append({
                    "type": "recurring_step_failure",
                    "step": step,
                    "count": count,
                    "severity": "high" if count > 10 else "medium",
                })

        # Pattern: performance degradation over time. Type-checked
        # access so a None elapsed_seconds doesn't crash the sum.
        def _elapsed(rows: list[dict[str, Any]]) -> list[float]:
            return [
                float(r["elapsed_seconds"]) for r in rows
                if isinstance(r.get("elapsed_seconds"), (int, float))
            ]

        if len(history) >= 20:
            recent_times = _elapsed(history[-10:])
            older_times = _elapsed(history[-20:-10])
            if recent_times and older_times:
                recent_avg = sum(recent_times) / len(recent_times)
                older_avg = sum(older_times) / len(older_times)
                if recent_avg > older_avg * 1.5:
                    patterns.append({
                        "type": "performance_degradation",
                        "recent_avg_ms": round(recent_avg * 1000),
                        "older_avg_ms": round(older_avg * 1000),
                        "severity": "medium",
                    })

        # Pattern: burst failures (multiple failures in short window)
        failure_times = [
            float(h["timestamp"]) for h in history
            if h.get("status") == "failed"
            and isinstance(h.get("timestamp"), (int, float))
        ]
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

        # Defensive `.get` so a malformed stats dict from a future
        # FeedbackStore version doesn't crash the whole loop.
        total_runs = stats.get("total_runs", 0)
        if total_runs == 0:
            return [{"type": "no_data", "action": "Run engine at least once to generate learning data"}]

        success_rate = stats.get("success_rate", 1.0)
        # Low success rate
        if success_rate < 0.9:
            errors = stats.get("common_errors", [])
            recs.append({
                "type": "improve_reliability",
                "priority": "high",
                "success_rate": success_rate,
                "action": f"Fix top errors: {errors[:2]}" if errors else "Investigate failure causes",
            })

        # Slow execution
        avg_elapsed = stats.get("avg_elapsed", 0)
        if avg_elapsed > 5.0:
            recs.append({
                "type": "optimize_speed",
                "priority": "medium",
                "avg_elapsed": avg_elapsed,
                "action": "Profile slow steps and optimize model calls",
            })

        # Low quality scores
        avg_quality = stats.get("avg_quality")
        if avg_quality is not None and avg_quality < 7.0:
            recs.append({
                "type": "improve_quality",
                "priority": "medium",
                "avg_quality": avg_quality,
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
        if stats.get("total_runs", 0) == 0:
            return "unknown"
        success_rate = stats.get("success_rate", 1.0)
        if success_rate < 0.7:
            return "critical"
        if success_rate < 0.9:
            return "warning"
        if stats.get("trend") == "declining":
            return "watch"
        return "healthy"

    @staticmethod
    def _system_success_rate(all_stats: dict[str, dict[str, Any]]) -> float:
        total_runs = sum(s.get("total_runs", 0) for s in all_stats.values())
        total_completed = sum(s.get("completed", 0) for s in all_stats.values())
        return round(total_completed / total_runs, 4) if total_runs else 0
