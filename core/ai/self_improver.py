"""SelfImprover — AI that learns from its own mistakes and improves.

After every cycle:
  1. Review what decisions were made
  2. Check outcomes (did it work?)
  3. If mistake → record WHY and HOW to prevent
  4. If success → reinforce the strategy
  5. Adjust confidence and strategy weights

The AI literally gets better every day.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("self_improver")


class SelfImprover:
    """Analyzes AI's own performance and adjusts strategies."""

    def __init__(self) -> None:
        self._experience = None
        self._improvement_count = 0

    def _get_experience(self):
        if self._experience is None:
            from core.ai.experience import get_experience
            self._experience = get_experience()
        return self._experience

    # ── Post-Cycle Review ────────────────────────────────────

    def review_cycle(self, cycle_result: dict[str, Any]) -> dict[str, Any]:
        """Review a completed cycle and learn from it."""
        exp = self._get_experience()
        improvements: list[str] = []
        mistakes_found = 0
        strategies_reinforced = 0

        phases = cycle_result.get("phases", {})

        # Review analysis phase
        analysis = phases.get("analysis", {})
        engines_run = analysis.get("engines_run", 0)
        insights = analysis.get("insights", 0)

        if engines_run > 0 and insights == 0:
            exp.record_mistake(
                "low_insight_cycle",
                f"Ran {engines_run} engines but found 0 insights",
                cause="Engines may need better data or different parameters",
                prevention="Check data quality before running engines. Try different engine combination.",
                severity="low",
            )
            mistakes_found += 1
            improvements.append("Need to improve data quality for better insights")

        # Review decision phase
        decisions = phases.get("decisions", {})
        proposed = decisions.get("proposed", 0)

        if insights > 5 and proposed == 0:
            exp.record_mistake(
                "insights_not_actioned",
                f"Had {insights} insights but proposed 0 actions",
                cause="Decision executor may not be converting insights to actions",
                prevention="Review decision thresholds. Lower confidence requirements.",
                severity="medium",
            )
            mistakes_found += 1

        # Review execution phase
        execution = phases.get("execution", {})
        executed = execution.get("executed", 0)
        failed = execution.get("failed", 0)

        if failed > 0:
            exp.record_mistake(
                "execution_failure",
                f"{failed} actions failed to execute",
                cause="API errors or invalid parameters",
                prevention="Validate parameters before execution. Check API connectivity.",
                severity="high" if failed > 2 else "medium",
            )
            mistakes_found += 1

        if executed > 0:
            exp.learn_strategy(
                f"executed_{executed}_actions",
                "execution",
                effectiveness=0.7,
                notes=f"Successfully executed {executed} actions",
            )
            strategies_reinforced += 1

        # Review learning phase
        learning = phases.get("learning", {})
        weight_updates = learning.get("weight_updates", 0)
        if weight_updates > 0:
            strategies_reinforced += 1

        # Duration analysis
        duration = cycle_result.get("duration_s", 0)
        if duration > 60:
            improvements.append(f"Cycle took {duration:.0f}s — optimize for speed")

        self._improvement_count += 1

        return {
            "improvements": improvements,
            "mistakes_found": mistakes_found,
            "strategies_reinforced": strategies_reinforced,
            "total_reviews": self._improvement_count,
        }

    # ── Decision Enhancement ─────────────────────────────────

    def enhance_decision(self, decision_type: str, proposed_action: dict[str, Any]) -> dict[str, Any]:
        """Enhance a proposed decision with past experience."""
        exp = self._get_experience()

        # Check past decisions of same type
        past = exp.get_similar_decisions(decision_type, limit=10)
        success_rate = exp.get_success_rate(decision_type)

        # Check for related mistakes
        mistakes = exp.get_mistakes(decision_type, limit=5)

        enhanced = dict(proposed_action)
        warnings = []
        adjustments = []

        # Adjust confidence based on past success rate
        if success_rate["total"] >= 5:
            rate = success_rate["success_rate"]
            original_confidence = enhanced.get("confidence", 0.5)
            # Blend with historical success rate
            adjusted_confidence = (original_confidence * 0.6) + (rate * 0.4)
            enhanced["confidence"] = round(adjusted_confidence, 3)
            enhanced["confidence_source"] = f"adjusted from {original_confidence:.2f} based on {success_rate['total']} past decisions ({rate:.0%} success)"
            adjustments.append(f"Confidence adjusted: {original_confidence:.2f} → {adjusted_confidence:.2f}")

        # Add warnings from past mistakes
        for mistake in mistakes:
            warnings.append({
                "type": mistake["mistake_type"],
                "description": mistake["description"],
                "prevention": mistake["prevention"],
            })

        # Get best strategy for this category
        strategies = exp.get_best_strategies(decision_type, limit=3)
        if strategies:
            enhanced["recommended_strategies"] = [
                {"strategy": s["strategy"][:200], "effectiveness": s["effectiveness"]}
                for s in strategies
            ]

        enhanced["warnings"] = warnings
        enhanced["adjustments"] = adjustments
        enhanced["experience_data_points"] = success_rate["total"]

        return enhanced

    # ── Performance Analysis ─────────────────────────────────

    def analyze_performance(self) -> dict[str, Any]:
        """Comprehensive self-analysis of AI performance."""
        exp = self._get_experience()
        summary = exp.get_knowledge_summary()

        # Find weak areas
        weak_areas = []
        strong_areas = []

        # Check decision types
        conn = exp._get_conn()
        types = conn.execute(
            "SELECT DISTINCT decision_type FROM decision_outcomes"
        ).fetchall()

        for row in types:
            dtype = row["decision_type"]
            rate = exp.get_success_rate(dtype)
            if rate["total"] >= 3:
                if rate["success_rate"] < 0.4:
                    weak_areas.append({
                        "area": dtype,
                        "success_rate": rate["success_rate"],
                        "recommendation": f"Improve {dtype} — only {rate['success_rate']:.0%} success rate",
                    })
                elif rate["success_rate"] > 0.7:
                    strong_areas.append({
                        "area": dtype,
                        "success_rate": rate["success_rate"],
                    })

        # Recent mistakes
        recent_mistakes = exp.get_mistakes(limit=10)
        mistake_patterns = {}
        for m in recent_mistakes:
            mt = m["mistake_type"]
            mistake_patterns[mt] = mistake_patterns.get(mt, 0) + 1

        recurring_issues = [
            {"type": k, "count": v, "severity": "high" if v > 3 else "medium"}
            for k, v in mistake_patterns.items() if v > 1
        ]

        return {
            "knowledge": summary,
            "weak_areas": weak_areas,
            "strong_areas": strong_areas,
            "recurring_issues": recurring_issues,
            "improvement_reviews": self._improvement_count,
            "recommendation": self._generate_recommendation(weak_areas, recurring_issues),
        }

    def _generate_recommendation(self, weak_areas: list, recurring_issues: list) -> str:
        """Generate top recommendation for improvement."""
        if recurring_issues:
            worst = max(recurring_issues, key=lambda x: x["count"])
            return f"Focus on fixing '{worst['type']}' — occurred {worst['count']} times"
        if weak_areas:
            worst = min(weak_areas, key=lambda x: x["success_rate"])
            return f"Improve '{worst['area']}' strategy — currently {worst['success_rate']:.0%} success rate"
        return "System performing well. Continue monitoring."

    # ── Auto-Adjustment ──────────────────────────────────────

    def get_adjusted_parameters(self, engine_name: str) -> dict[str, Any]:
        """Get AI-adjusted parameters for an engine based on experience."""
        exp = self._get_experience()

        # Get past decision outcomes for this engine
        conn = exp._get_conn()
        successes = conn.execute(
            "SELECT decision_data FROM decision_outcomes WHERE engine = ? AND success = 1 ORDER BY created_at DESC LIMIT 10",
            (engine_name,),
        ).fetchall()

        failures = conn.execute(
            "SELECT decision_data FROM decision_outcomes WHERE engine = ? AND success = 0 ORDER BY created_at DESC LIMIT 10",
            (engine_name,),
        ).fetchall()

        adjustments = {}

        # Analyze what parameters led to success vs failure
        if successes and failures:
            import json
            success_data = [json.loads(s["decision_data"]) for s in successes]
            failure_data = [json.loads(f["decision_data"]) for f in failures]

            # Find common keys
            all_keys = set()
            for d in success_data + failure_data:
                if isinstance(d, dict):
                    all_keys.update(d.keys())

            for key in all_keys:
                success_vals = [d.get(key) for d in success_data if isinstance(d, dict) and key in d]
                failure_vals = [d.get(key) for d in failure_data if isinstance(d, dict) and key in d]

                # Compare numeric values
                s_nums = [v for v in success_vals if isinstance(v, (int, float))]
                f_nums = [v for v in failure_vals if isinstance(v, (int, float))]

                if s_nums and f_nums:
                    s_avg = sum(s_nums) / len(s_nums)
                    f_avg = sum(f_nums) / len(f_nums)
                    if abs(s_avg - f_avg) > 0.1 * max(abs(s_avg), abs(f_avg), 1):
                        adjustments[key] = {
                            "recommended": round(s_avg, 3),
                            "avoid": round(f_avg, 3),
                            "reason": f"Success avg: {s_avg:.2f}, Failure avg: {f_avg:.2f}",
                        }

        return {
            "engine": engine_name,
            "adjustments": adjustments,
            "data_points": len(successes) + len(failures) if successes and failures else 0,
        }
