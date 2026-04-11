"""Strategy Optimizer — auto-adjusts decision strategy based on outcomes.

If "product_launch" keeps failing → lower its priority weight.
If "pricing_optimization" keeps winning → boost its weight.

Learns from OutcomeTracker patterns and adjusts goal_weights
used by IntelligenceLoop._stage_decide().
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.strategy")

try:
    from core.memory.storage_config import get_path
    _STRATEGY_PATH = os.path.join(get_path("learning"), "strategy_weights.json")
except Exception:
    _STRATEGY_PATH = "/tmp/shopai_strategy_weights.json"

# Default goal weights (used by IntelligenceLoop._stage_decide)
_DEFAULT_WEIGHTS = {
    "maximize_profit": {
        "product_launch": 1.0,
        "pricing_optimization": 1.0,
        "customer_retention": 1.0,
        "aov_increase": 1.0,
        "data_collection": 0.5,
    },
    "grow_customers": {
        "product_launch": 0.8,
        "pricing_optimization": 0.6,
        "customer_retention": 1.2,
        "aov_increase": 0.7,
        "data_collection": 0.5,
    },
    "increase_aov": {
        "product_launch": 0.7,
        "pricing_optimization": 1.0,
        "customer_retention": 0.8,
        "aov_increase": 1.3,
        "data_collection": 0.5,
    },
}


class StrategyOptimizer:
    """Auto-adjusts decision strategy weights from outcome data."""

    def __init__(self, *, llm: Any = None) -> None:
        self._adjustments: dict[str, dict[str, float]] = {}
        self._llm = llm
        self._load()

    def get_adjusted_weights(self, goal: str) -> dict[str, float]:
        """Get goal weights with learning adjustments applied."""
        base = dict(_DEFAULT_WEIGHTS.get(goal, _DEFAULT_WEIGHTS["maximize_profit"]))
        adj = self._adjustments.get(goal, {})
        for key, delta in adj.items():
            if key in base:
                base[key] = max(0.1, min(2.0, base[key] + delta))
        return base

    def update_from_outcomes(self) -> dict[str, Any]:
        """Pull outcome data and adjust strategy weights."""
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            changes = []

            for engine_key in ("intelligence_loop", "full_system_loop"):
                entries = ot._load(engine_key)
                outcomes = [e for e in entries if e.get("outcome") is not None]

                # Group by decision_type
                by_type: dict[str, dict] = {}
                for e in outcomes:
                    dt = e.get("decision", {}).get("decision_type", "unknown")
                    if dt == "unknown":
                        continue
                    if dt not in by_type:
                        by_type[dt] = {"success": 0, "fail": 0}
                    if e.get("success"):
                        by_type[dt]["success"] += 1
                    else:
                        by_type[dt]["fail"] += 1

                # Adjust weights based on success rates
                for dt, counts in by_type.items():
                    total = counts["success"] + counts["fail"]
                    if total < 2:
                        continue
                    rate = counts["success"] / total

                    # Determine adjustment
                    if rate > 0.7:
                        delta = 0.1  # Boost winning strategy
                        changes.append(f"{dt}: success rate {rate:.0%} → boost +0.1")
                    elif rate < 0.3:
                        delta = -0.15  # Reduce failing strategy
                        changes.append(f"{dt}: success rate {rate:.0%} → reduce -0.15")
                    else:
                        delta = 0.0

                    if delta != 0:
                        for goal in _DEFAULT_WEIGHTS:
                            if goal not in self._adjustments:
                                self._adjustments[goal] = {}
                            current = self._adjustments[goal].get(dt, 0)
                            self._adjustments[goal][dt] = round(max(-0.5, min(0.5, current + delta)), 2)

            self._save()
            return {"changes": changes, "adjustments": self._adjustments}

        except Exception as exc:
            logger.warning("Strategy update failed: %s", exc)
            return {"changes": [], "error": str(exc)}

    def get_strategy_report(self) -> dict[str, Any]:
        """Report on current strategy state."""
        report = {}
        for goal in _DEFAULT_WEIGHTS:
            base = _DEFAULT_WEIGHTS[goal]
            adjusted = self.get_adjusted_weights(goal)
            report[goal] = {
                "base_weights": base,
                "adjusted_weights": adjusted,
                "changes": {k: round(adjusted[k] - base[k], 2) for k in base if adjusted[k] != base[k]},
            }
        return report

    def auto_pilot(self, current_goal: str, performance_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Auto-pilot mode: automatically determine the best strategy.

        Analyzes recent outcomes and recommends whether to:
          - Continue current goal
          - Switch to a different goal
          - Adjust strategy weights
        """
        self.update_from_outcomes()
        weights_by_goal = {}
        for goal in _DEFAULT_WEIGHTS:
            weights_by_goal[goal] = self.get_adjusted_weights(goal)

        # Score each goal based on adjusted weights
        goal_scores = {}
        for goal, weights in weights_by_goal.items():
            avg_weight = sum(weights.values()) / max(len(weights), 1)
            max_weight = max(weights.values())
            goal_scores[goal] = round(avg_weight * 0.6 + max_weight * 0.4, 3)

        best_goal = max(goal_scores, key=goal_scores.get)
        should_switch = best_goal != current_goal and goal_scores[best_goal] > goal_scores.get(current_goal, 0) + 0.1

        # Get strategy for best goal
        recommended_weights = weights_by_goal[best_goal]
        top_strategy = max(recommended_weights, key=recommended_weights.get)

        result = {
            "current_goal": current_goal,
            "recommended_goal": best_goal,
            "should_switch": should_switch,
            "goal_scores": goal_scores,
            "recommended_strategy": top_strategy,
            "recommended_weights": recommended_weights,
        }

        if should_switch:
            result["switch_reason"] = f"'{best_goal}' scores {goal_scores[best_goal]:.3f} vs current '{current_goal}' at {goal_scores.get(current_goal, 0):.3f}"
        else:
            result["stay_reason"] = f"'{current_goal}' is optimal or close enough"

        # Performance-based refinement
        if performance_data:
            revenue_trend = performance_data.get("revenue_trend", "stable")
            if revenue_trend == "declining" and current_goal == "maximize_profit":
                result["warning"] = "Revenue declining — consider switching to grow_customers"
            elif revenue_trend == "growing" and current_goal != "maximize_profit":
                result["opportunity"] = "Revenue growing — maximize_profit may yield higher returns"

        return result

    def _load(self) -> None:
        if os.path.exists(_STRATEGY_PATH):
            try:
                with open(_STRATEGY_PATH) as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._adjustments = data
            except Exception:
                pass

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STRATEGY_PATH), exist_ok=True)
            tmp = _STRATEGY_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._adjustments, f)
            os.replace(tmp, _STRATEGY_PATH)
        except Exception as exc:
            logger.warning("Strategy save failed: %s", exc)

    # ── LLM-backed strategy refinement ───────────────────────

    def refine_with_llm(
        self,
        current_goal: str,
        performance_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask the LLM to interpret the heuristic auto_pilot output
        and recommend refinements.

        Returns:
            {
                "heuristic": <auto_pilot output>,
                "llm": {recommended_goal, weight_changes,
                        rationale, confidence, risks} or {"error": "..."},
                "source": "llm" | "heuristic_only",
            }

        The heuristic auto_pilot already detects coarse signals
        (declining revenue → switch to grow_customers). The LLM
        layer adds judgement: it can weigh trade-offs the
        heuristic can't, like "revenue is declining BUT margin is
        still healthy, so don't panic-switch goals — tighten ad
        spend instead".
        """
        heuristic = self.auto_pilot(current_goal, performance_data=performance_data)
        result: dict[str, Any] = {
            "heuristic": heuristic,
            "llm": None,
            "source": "heuristic_only",
        }

        llm = self._get_llm()
        if llm is None:
            return result
        try:
            if not llm.is_available():
                return result
        except Exception:  # noqa: BLE001
            return result

        try:
            from core.system.prompt_library import get_prompt
        except Exception:  # noqa: BLE001
            return result
        template = get_prompt("strategy.refine")
        if template is None:
            return result

        try:
            import json as _json
            heuristic_json = _json.dumps(heuristic, default=str)[:2000]
            performance_json = _json.dumps(performance_data or {}, default=str)[:1000]
        except Exception:  # noqa: BLE001
            return result

        rendered = template.render(
            current_goal=current_goal,
            heuristic_summary=heuristic_json,
            performance_summary=performance_json,
        )

        try:
            structured = llm.ask_structured(
                role=template.role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint,
            )
        except Exception as exc:  # noqa: BLE001
            result["llm"] = {"error": str(exc)[:200]}
            return result

        if not getattr(structured, "ok", False):
            result["llm"] = {"error": structured.error or "unparseable"}
            return result

        data = structured.data or {}
        try:
            weight_changes = data.get("weight_changes") or {}
            if not isinstance(weight_changes, dict):
                weight_changes = {}
            normalized_changes: dict[str, float] = {}
            for k, v in list(weight_changes.items())[:8]:
                try:
                    normalized_changes[str(k)] = max(-1.0, min(1.0, float(v)))
                except (TypeError, ValueError):
                    continue
            risks = data.get("risks") or []
            if not isinstance(risks, list):
                risks = []
            result["llm"] = {
                "recommended_goal": str(data.get("recommended_goal", current_goal)),
                "weight_changes": normalized_changes,
                "rationale": str(data.get("rationale", ""))[:500],
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                "risks": [str(r) for r in risks[:5]],
            }
            result["source"] = "llm"
        except (TypeError, ValueError) as exc:
            result["llm"] = {"error": f"normalization failed: {exc}"}
        return result

    def _get_llm(self) -> Any:
        """Lazily resolve the LLM adapter."""
        if self._llm is not None:
            return self._llm
        try:
            from core.system.llm_adapter import get_llm
            return get_llm()
        except Exception:  # noqa: BLE001
            return None
