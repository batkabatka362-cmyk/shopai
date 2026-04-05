"""Intelligence Cycle - the 10-stage AI intelligence loop.

NOT a workflow. An intelligence architecture.

Stages:
  1. DATA       - raw input enters
  2. FILTER     - noise removed
  3. FEATURE    - raw -> AI signals  
  4. MEMORY     - consult past experience
  5. DECISION   - choose action based on memory
  6. EXECUTION  - do it
  7. RESULT     - capture what happened
  8. EVALUATION - score the outcome (1-5)
  9. LEARNING   - extract patterns/insights
  10. UPDATE    - update memory for next cycle

Gold Rules:
  - data -> decision directly = FORBIDDEN
  - features -> REQUIRED before memory
  - memory -> REQUIRED before decision
  - evaluation -> REQUIRED after execution
  - learning -> REQUIRED after evaluation
  - cycle never stops
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence_cycle")


class IntelligenceCycle:
    """10-stage intelligence cycle - every engine decision must go through this."""

    def __init__(self) -> None:
        self._data_arch = None
        self._memory_intel = None
        self._cycles_run = 0
        self._last_result: dict[str, Any] = {}

    def _ensure_init(self) -> None:
        if not self._data_arch:
            from core.data.architecture import get_data_architecture
            self._data_arch = get_data_architecture()
        if not self._memory_intel:
            from core.memory.intelligence import get_memory_intelligence
            self._memory_intel = get_memory_intelligence()

    # == FULL CYCLE ================================================

    def run(self, category: str, raw_data: dict, action_fn=None,
            store_id: str = "") -> dict[str, Any]:
        """Run one full intelligence cycle.

        Args:
            category: Domain (product, pricing, marketing, etc.)
            raw_data: Input data
            action_fn: Optional callable(decision) -> result
            store_id: Store identifier

        Returns:
            Cycle result with all stages
        """
        self._ensure_init()
        start = time.monotonic()
        cycle_id = f"ic_{self._cycles_run}_{int(time.time())}"

        stages: dict[str, Any] = {}

        # Stage 1: DATA - capture raw input
        stages["data"] = {"fields": len(raw_data), "category": category}

        # Stage 2: FILTER - remove noise
        filtered = self._filter(raw_data)
        stages["filter"] = {
            "input_fields": len(raw_data),
            "output_fields": len(filtered),
            "removed": len(raw_data) - len(filtered),
        }

        # Stage 3: FEATURE - transform to AI signals
        features = self._extract_features(category, filtered)
        stages["feature"] = {
            "features_extracted": len(features),
            "features": list(features.keys()),
        }

        # Stage 4: MEMORY - consult past experience
        memory_context = self._consult_memory(category)
        stages["memory"] = {
            "total_memories": memory_context.get("total_memories", 0),
            "rules": len(memory_context.get("rules", [])),
            "patterns": len(memory_context.get("patterns", [])),
            "strategies": len(memory_context.get("strategies", [])),
            "failures": len(memory_context.get("failures", [])),
        }

        # Stage 5: DECISION - choose action
        decision = self._decide(category, features, memory_context)
        stages["decision"] = {
            "action": decision.get("action", "none"),
            "confidence": decision.get("confidence", 0),
            "memory_informed": decision.get("memory_informed", False),
            "rules_applied": decision.get("rules_applied", 0),
        }

        # Stage 6: EXECUTION - do it (if action_fn provided)
        execution_result = {}
        if action_fn and decision.get("action") != "none":
            try:
                execution_result = action_fn(decision) or {}
                stages["execution"] = {"status": "executed", "has_result": bool(execution_result)}
            except Exception as exc:
                execution_result = {"error": str(exc)}
                stages["execution"] = {"status": "failed", "error": str(exc)[:80]}
        else:
            stages["execution"] = {"status": "skipped" if not action_fn else "no_action"}

        # Stage 7: RESULT - capture outcome
        result = self._capture_result(category, decision, execution_result, store_id)
        stages["result"] = result

        # Stage 8: EVALUATION - score the outcome
        score = self._evaluate(category, decision, execution_result, features)
        stages["evaluation"] = {"score": score, "rating": self._score_label(score)}

        # Stage 9: LEARNING - extract insights
        learning = self._learn(category, features, decision, execution_result, score)
        stages["learning"] = learning

        # Stage 10: UPDATE - update memory
        update = self._update_memory(category, filtered, decision, execution_result, score, features)
        stages["update"] = update

        elapsed = time.monotonic() - start
        self._cycles_run += 1

        result = {
            "cycle_id": cycle_id,
            "category": category,
            "stages": stages,
            "score": score,
            "action": decision.get("action", "none"),
            "memory_informed": decision.get("memory_informed", False),
            "duration_s": round(elapsed, 3),
        }
        self._last_result = result

        logger.info("Intelligence cycle [%s]: action=%s score=%.1f memory=%s %.3fs",
                    category, decision.get("action", "none"), score,
                    decision.get("memory_informed", False), elapsed)

        return result


    # == Stage 2: FILTER ===========================================

    @staticmethod
    def _filter(data: dict) -> dict:
        """Remove noise, empty values, irrelevant fields."""
        filtered = {}
        skip_keys = {"_id", "__v", "admin_graphql_api_id", "presentment_prices"}
        for k, v in data.items():
            if k.startswith("_") and k not in ("_quality",):
                continue
            if k in skip_keys:
                continue
            if v is None or v == "" or v == [] or v == {}:
                continue
            filtered[k] = v
        return filtered

    # == Stage 3: FEATURE ==========================================

    def _extract_features(self, category: str, data: dict) -> dict[str, Any]:
        """Transform raw data into AI-understandable signals."""
        return self._memory_intel._extract_features(category, data)

    # == Stage 4: MEMORY ===========================================

    def _consult_memory(self, category: str) -> dict[str, Any]:
        """Consult memory before making any decision."""
        return self._memory_intel.retrieve_for_decision(category)

    # == Stage 5: DECISION =========================================

    @staticmethod
    def _decide(category: str, features: dict, memory: dict) -> dict[str, Any]:
        """Make decision based on features + memory. NO random decisions."""
        rules = memory.get("rules", [])
        strategies = memory.get("strategies", [])
        best_events = memory.get("best_events", [])
        failures = memory.get("failures", [])

        decision: dict[str, Any] = {
            "action": "analyze",  # Default: gather more data
            "confidence": 0.3,
            "reason": "default_action",
            "memory_informed": memory.get("total_memories", 0) > 0,
            "rules_applied": 0,
        }

        # Apply strategies first (highest level)
        if strategies:
            strategy = strategies[0]
            s_content = strategy.get("content", {})
            if isinstance(s_content, dict) and s_content.get("rules"):
                decision["reason"] = f"strategy:{s_content.get('strategy', '')[:50]}"
                decision["confidence"] = min(0.9, strategy.get("confidence", 0.5) + 0.1)

        # Apply rules
        rules_applied = 0
        for rule in rules:
            r_content = rule.get("content", {})
            if not isinstance(r_content, dict):
                continue
            recommended = r_content.get("recommended_action", rule.get("action", ""))
            if recommended == "prefer":
                decision["confidence"] = min(1.0, decision["confidence"] + 0.1)
                rules_applied += 1
            elif recommended == "avoid":
                decision["confidence"] = max(0.1, decision["confidence"] - 0.1)
                rules_applied += 1
        decision["rules_applied"] = rules_applied

        # Learn from best events
        if best_events:
            top = best_events[0]
            if top.get("action"):
                decision["action"] = top["action"]
                decision["reason"] = f"best_event:score={top.get('score', 0):.1f}"
                decision["confidence"] = min(0.9, decision["confidence"] + 0.15)

        # Avoid failure patterns
        for fail in failures:
            if fail.get("action") == decision.get("action"):
                decision["confidence"] = max(0.1, decision["confidence"] - 0.2)
                decision["reason"] += f"|failure_warning:{fail.get('action')}"

        return decision

    # == Stage 7: RESULT ===========================================

    def _capture_result(self, category: str, decision: dict,
                        execution_result: dict, store_id: str) -> dict[str, Any]:
        """Capture result in data architecture."""
        action_id = f"{category}_{int(time.time())}"
        self._data_arch.record_action(
            action_id=action_id,
            action_type=decision.get("action", "unknown"),
            action_data={"confidence": decision.get("confidence", 0),
                         "reason": decision.get("reason", "")},
            store_id=store_id,
        )
        if execution_result:
            self._data_arch.attach_result(action_id, execution_result)
        return {"action_id": action_id, "captured": True}


    # == Stage 8: EVALUATION =======================================

    @staticmethod
    def _evaluate(category: str, decision: dict, result: dict,
                  features: dict) -> float:
        """Score the outcome 1-5."""
        score = 3.0  # Neutral default

        if not result:
            return 2.5  # No result = slightly negative

        # Error = bad
        if result.get("error"):
            return 1.5

        # Success indicators
        if result.get("success") or result.get("status") == "success":
            score += 1.0

        # Revenue/profit impact
        revenue = float(result.get("revenue_impact", result.get("revenue", 0)) or 0)
        if revenue > 0:
            score += 0.5
        elif revenue < 0:
            score -= 0.5

        # Conversion impact
        conversion = float(result.get("conversion_impact", result.get("conversion_rate", 0)) or 0)
        if conversion > 0:
            score += 0.3

        # Confidence alignment
        confidence = decision.get("confidence", 0.5)
        if confidence > 0.7 and score >= 3.5:
            score += 0.2  # High confidence confirmed
        elif confidence > 0.7 and score < 2.5:
            score -= 0.3  # High confidence was wrong

        return max(1.0, min(5.0, round(score, 1)))

    # == Stage 9: LEARNING =========================================

    def _learn(self, category: str, features: dict, decision: dict,
               result: dict, score: float) -> dict[str, Any]:
        """Extract learning from this cycle."""
        learning: dict[str, Any] = {"insights": [], "pattern_check": False}

        # Record failure if score is bad
        if score <= 2.0:
            root_cause = ""
            if result.get("error"):
                root_cause = str(result["error"])[:100]
            elif decision.get("action") and not decision.get("memory_informed"):
                root_cause = "decision_without_memory"
            elif decision.get("confidence", 0) > 0.7:
                root_cause = "overconfident_failure"

            self._memory_intel.record_failure(
                category=category,
                failure_data={"features": features, "decision": decision.get("action", ""),
                              "result_summary": {k: v for k, v in result.items() if k != "raw"}},
                root_cause=root_cause,
                severity="critical" if score <= 1.5 else "medium",
            )
            learning["insights"].append(f"failure_recorded:{root_cause or 'unknown'}")

        # Record success pattern
        if score >= 4.0:
            learning["insights"].append(f"success_pattern:{decision.get('action', '')}:score={score}")

        # Check if decision confidence matched reality
        confidence = decision.get("confidence", 0.5)
        if abs(confidence - score / 5.0) > 0.3:
            learning["insights"].append(f"confidence_mismatch:predicted={confidence:.2f},actual={score/5:.2f}")

        learning["pattern_check"] = True
        return learning

    # == Stage 10: MEMORY UPDATE ===================================

    def _update_memory(self, category: str, data: dict, decision: dict,
                       result: dict, score: float, features: dict) -> dict[str, Any]:
        """Update memory with this cycle's outcome."""
        # Create decision memory (the most important type)
        mid = self._memory_intel.create_from_decision(
            category=category,
            input_data=data,
            action=decision.get("action", ""),
            result=result,
            score=score,
            tags=[category, decision.get("action", "")],
        )

        # Also capture in data architecture
        self._data_arch.capture(
            domain="decision",
            data={
                "choice": decision.get("action", ""),
                "confidence": decision.get("confidence", 0),
                "memory_used": decision.get("memory_informed", False),
                "rules_applied": decision.get("rules_applied", 0),
                "score": score,
            },
            source="intelligence_cycle",
            score=score,
        )

        return {"memory_id": mid, "updated": mid > 0}

    # == HELPERS ===================================================

    @staticmethod
    def _score_label(score: float) -> str:
        if score >= 4.5:
            return "excellent"
        elif score >= 3.5:
            return "good"
        elif score >= 2.5:
            return "neutral"
        elif score >= 1.5:
            return "poor"
        return "terrible"

    def get_stats(self) -> dict[str, Any]:
        """Get cycle statistics."""
        self._ensure_init()
        return {
            "cycles_run": self._cycles_run,
            "data_architecture": self._data_arch.get_stats(),
            "memory_intelligence": self._memory_intel.get_stats(),
            "last_result": {
                "category": self._last_result.get("category", ""),
                "score": self._last_result.get("score", 0),
                "action": self._last_result.get("action", ""),
            } if self._last_result else {},
        }

    def get_last_result(self) -> dict[str, Any]:
        return self._last_result


# Singleton
_instance: IntelligenceCycle | None = None


def get_intelligence_cycle() -> IntelligenceCycle:
    global _instance
    if _instance is None:
        _instance = IntelligenceCycle()
    return _instance
