"""RootCauseAnalyzer — when a decision fails, analyze WHY.

Learning system мэддэг "юу" fail хийснийг. RootCauseAnalyzer мэддэг "ЯАГААД".

Factor attribution: Амжилттай case-с юугаараа ялгаатай?
Counterfactual: Хоёрдахь сонголт амжилттай байх байсан уу?
Lesson generation: "Ийм нөхцөлд ингэж хийхгүй" гэсэн rule.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("learning.root_cause")

# Factors to compare between successes and failures
ANALYSIS_FACTORS = [
    "health_grade", "churn_pct", "stockout_risk", "confidence_score",
    "net_margin", "critical_alerts", "competitor_active", "data_quality",
]

# Grade ordering for comparison
GRADE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1, "?": 0}


class RootCauseAnalyzer:
    """Analyzes WHY decisions fail and generates prevention rules.

    Usage:
        analyzer = RootCauseAnalyzer(episodic_memory)
        result = analyzer.analyze_failure(failed_episode)
        # result = {
        #   "root_causes": [...],
        #   "contributing_factors": [...],
        #   "lesson": "When health=D AND competitor_active → don't raise price",
        #   "prevention_rule": {...},
        # }
    """

    def __init__(self, episodic_memory: Any = None) -> None:
        self._memory = episodic_memory

    def analyze_failure(self, failed_episode: dict[str, Any]) -> dict[str, Any]:
        """Analyze a failed decision episode to find root causes.

        Compares the failed episode's context to successful episodes
        of the same decision type. Differences = likely causes.
        """
        if not failed_episode:
            return {"root_causes": [], "lesson": "", "contributing_factors": []}

        decision_type = failed_episode.get("decision_type", "general")
        failed_context = failed_episode.get("context", {})
        action = failed_episode.get("action", "unknown")

        # Get successful episodes for comparison
        successes = self._get_successes(decision_type)

        # Factor attribution: what's different between this failure and successes?
        contributing_factors = self._factor_attribution(failed_context, successes)

        # Generate root causes
        root_causes = self._identify_root_causes(contributing_factors, failed_context)

        # Counterfactual: could a different action have worked?
        counterfactual = self._counterfactual(decision_type, failed_context)

        # Generate lesson
        lesson = self._generate_lesson(decision_type, action, root_causes, failed_context)

        # Generate prevention rule
        prevention_rule = self._generate_rule(decision_type, root_causes, failed_context)

        logger.info(
            "Root cause analysis for %s/%s: %d causes, lesson: %s",
            decision_type, action, len(root_causes), lesson[:80],
        )

        return {
            "decision_type": decision_type,
            "action": action,
            "root_causes": root_causes,
            "contributing_factors": contributing_factors,
            "counterfactual": counterfactual,
            "lesson": lesson,
            "prevention_rule": prevention_rule,
        }

    def analyze_pattern(self, decision_type: str | None = None) -> dict[str, Any]:
        """Analyze patterns across multiple failures of the same type."""
        if self._memory is None:
            return {"status": "no_memory"}

        try:
            failures = self._memory.get_failures(decision_type=decision_type) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RootCauseAnalyzer: memory.get_failures failed (%s)", exc,
            )
            return {
                "status": "memory_error",
                "decision_type": decision_type,
                "error": str(exc)[:120],
            }
        if not failures:
            return {"status": "no_failures", "decision_type": decision_type}

        # Count factor frequencies across failures
        factor_freq: dict[str, dict[str, int]] = {}
        for ep in failures:
            ctx = ep.get("context", {})
            for factor in ANALYSIS_FACTORS:
                val = ctx.get(factor)
                if val is not None:
                    if factor not in factor_freq:
                        factor_freq[factor] = {}
                    val_str = str(val)
                    factor_freq[factor][val_str] = factor_freq[factor].get(val_str, 0) + 1

        # Find common conditions in failures
        common_conditions = []
        for factor, values in factor_freq.items():
            total = sum(values.values())
            for val, count in values.items():
                if count / total >= 0.6:  # 60%+ of failures share this value
                    common_conditions.append({
                        "factor": factor,
                        "value": val,
                        "frequency": round(count / total * 100, 1),
                        "count": count,
                    })

        common_conditions.sort(key=lambda c: c["frequency"], reverse=True)

        return {
            "decision_type": decision_type,
            "total_failures": len(failures),
            "common_conditions": common_conditions,
            "insight": self._pattern_insight(common_conditions, decision_type),
        }

    def _get_successes(self, decision_type: str) -> list[dict[str, Any]]:
        """Get successful episodes of the same type for comparison."""
        if self._memory is None:
            return []
        try:
            all_episodes = self._memory.recall_similar({}, limit=50) or []
        except Exception as exc:  # noqa: BLE001
            # Memory backends can raise (DB locked, schema drift,
            # missing method on a stub). Don't let that crash the
            # whole root-cause analysis — return an empty success
            # set so the rest of the analyzer falls back gracefully.
            logger.warning(
                "RootCauseAnalyzer: memory.recall_similar failed (%s); "
                "no comparison successes available", exc,
            )
            return []
        return [
            ep for ep in all_episodes
            if isinstance(ep, dict)
            and ep.get("success")
            and ep.get("decision_type") == decision_type
        ]

    def _factor_attribution(
        self,
        failed_ctx: dict[str, Any],
        successes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Compare failed context to successful contexts. Differences = contributing factors."""
        if not successes:
            return [{"factor": "no_comparison_data", "note": "No successful episodes to compare against"}]

        # Compute average context values for successes
        success_avgs: dict[str, float] = {}
        for factor in ANALYSIS_FACTORS:
            vals = []
            for ep in successes:
                ctx = ep.get("context", {})
                v = ctx.get(factor)
                if isinstance(v, (int, float)):
                    vals.append(v)
                elif isinstance(v, str) and v in GRADE_ORDER:
                    vals.append(GRADE_ORDER[v])
                elif isinstance(v, bool):
                    vals.append(1.0 if v else 0.0)
            if vals:
                success_avgs[factor] = sum(vals) / len(vals)

        # Compare
        factors = []
        for factor in ANALYSIS_FACTORS:
            failed_val = failed_ctx.get(factor)
            if failed_val is None:
                continue

            # Normalize to numeric
            if isinstance(failed_val, str) and failed_val in GRADE_ORDER:
                failed_num = GRADE_ORDER[failed_val]
            elif isinstance(failed_val, bool):
                failed_num = 1.0 if failed_val else 0.0
            elif isinstance(failed_val, (int, float)):
                failed_num = float(failed_val)
            else:
                continue

            success_avg = success_avgs.get(factor)
            if success_avg is None:
                continue

            # Compute BOTH absolute and relative diff. The previous
            # `if abs(diff) > 0.5` threshold was unit-blind: a half-
            # grade health swing (1-5 scale) would correctly fire,
            # but a 6x churn_pct difference (0.05 vs 0.30) wouldn't
            # because abs(0.25) < 0.5. Now we accept either an
            # absolute diff > 0.5 (good for grade-style 1-5 scales)
            # OR a relative diff > 50% of the larger value (good
            # for fractional 0-1 scales like churn_pct/net_margin).
            diff = failed_num - success_avg
            both = max(abs(failed_num), abs(success_avg))
            relative = abs(diff) / both if both > 0 else 0.0
            if abs(diff) > 0.5 or relative > 0.5:
                direction = "higher" if diff > 0 else "lower"
                factors.append({
                    "factor": factor,
                    "failed_value": failed_val,
                    "success_avg": round(success_avg, 2),
                    "difference": round(diff, 2),
                    "relative_difference": round(relative, 3),
                    "direction": direction,
                    "impact": (
                        "high" if abs(diff) > 2 or relative > 0.8
                        else "medium"
                    ),
                })

        factors.sort(key=lambda f: abs(f["difference"]), reverse=True)
        return factors

    def _identify_root_causes(
        self,
        contributing_factors: list[dict[str, Any]],
        failed_ctx: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Identify root causes from contributing factors."""
        causes = []

        for factor in contributing_factors[:3]:  # Top 3 factors
            # Use .get() so the special-case "no_comparison_data"
            # entry returned by _factor_attribution when there are
            # no successful episodes to compare against doesn't
            # crash _identify_root_causes with KeyError. Skip any
            # factor that lacks both fields — it has no information.
            name = factor.get("factor")
            val = factor.get("failed_value")
            if name is None or val is None:
                continue

            if name == "health_grade" and val in ("D", "F"):
                causes.append({"cause": "Poor financial health", "factor": name, "value": val,
                              "explanation": f"Financial health was {val} — system should not have taken this risk"})
            elif name == "confidence_score" and isinstance(val, (int, float)) and val < 50:
                causes.append({"cause": "Low confidence decision", "factor": name, "value": val,
                              "explanation": f"Confidence was only {val}/100 — insufficient certainty"})
            elif name == "churn_pct" and isinstance(val, (int, float)) and val > 30:
                causes.append({"cause": "High customer churn", "factor": name, "value": val,
                              "explanation": f"Churn was at {val}% — customer base unstable"})
            elif name == "stockout_risk" and val:
                causes.append({"cause": "Inventory risk", "factor": name, "value": val,
                              "explanation": "Products were at stockout risk during decision"})
            elif name == "critical_alerts" and isinstance(val, (int, float)) and val > 0:
                causes.append({"cause": "Active critical alerts", "factor": name, "value": val,
                              "explanation": f"{int(val)} critical alerts active — system was already in trouble"})
            else:
                causes.append({"cause": f"Unfavorable {name}", "factor": name, "value": val,
                              "explanation": f"{name} was {val}, significantly different from successful decisions"})

        return causes

    def _counterfactual(self, decision_type: str, failed_ctx: dict[str, Any]) -> dict[str, Any]:
        """What if we had chosen differently?"""
        if self._memory is None:
            return {"available": False}

        # Look for successful episodes in similar context but different action
        try:
            similar = self._memory.recall_similar(failed_ctx, limit=10) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RootCauseAnalyzer: counterfactual recall_similar failed (%s)",
                exc,
            )
            return {"available": False, "error": str(exc)[:120]}
        alternatives = [
            ep for ep in similar
            if isinstance(ep, dict)
            and ep.get("success")
            and ep.get("decision_type") != decision_type
        ]

        if alternatives:
            best = alternatives[0]
            return {
                "available": True,
                "alternative_action": best.get("action", "?"),
                "alternative_type": best.get("decision_type", "?"),
                "outcome": "success",
                "note": f"In similar conditions, '{best.get('action', '?')}' succeeded",
            }

        return {"available": False, "note": "No successful alternatives found in similar conditions"}

    def _generate_lesson(
        self,
        decision_type: str,
        action: str,
        root_causes: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> str:
        """Generate a human-readable lesson from the failure."""
        if not root_causes:
            return f"{decision_type}/{action} failed — insufficient data to determine cause"

        conditions = []
        for cause in root_causes[:2]:
            conditions.append(f"{cause['factor']}={cause['value']}")

        return (
            f"{decision_type}/{action} FAILED when {' AND '.join(conditions)}. "
            f"Avoid this combination in the future."
        )

    def _generate_rule(
        self,
        decision_type: str,
        root_causes: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a prevention rule from the failure."""
        if not root_causes:
            return {}

        conditions = {}
        for cause in root_causes[:3]:
            factor = cause["factor"]
            val = cause["value"]
            if isinstance(val, bool):
                conditions[factor] = val
            elif isinstance(val, (int, float)):
                conditions[f"{factor}_threshold"] = val
            elif isinstance(val, str):
                conditions[factor] = val

        return {
            "decision_type": decision_type,
            "block_when": conditions,
            "severity": "veto" if len(root_causes) >= 2 else "warning",
            "generated_from": "root_cause_analysis",
        }

    def _pattern_insight(self, conditions: list[dict[str, Any]], decision_type: str | None) -> str:
        """Generate insight from failure pattern analysis."""
        if not conditions:
            return "No clear pattern in failures"

        top = conditions[0]
        dt = decision_type or "all decisions"
        return (
            f"Most common condition in {dt} failures: "
            f"{top['factor']}={top['value']} ({top['frequency']}% of failures). "
            f"Consider blocking {dt} when {top['factor']}={top['value']}."
        )
