"""LearningLoop — execution→result→evaluation→memory update→rule generation.

The system gets smarter after EVERY action.
Failures are the best teachers — they generate rules.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.learning")


class LearningLoop:
    """Continuous learning from every execution."""

    def __init__(self) -> None:
        self._memory = None
        self._memory_intel = None
        self._data_arch = None
        self._total_learnings = 0

    def _get_memory(self):
        """Route through UnifiedMemory instead of directly
        importing get_brain_memory. Same Fix D/I pattern
        applied elsewhere — UnifiedMemory is the single
        entry point for the 6-layer brain memory."""
        if not self._memory:
            from core.memory.unified_memory import get_unified_memory
            self._memory = get_unified_memory().get_brain_memory()
        return self._memory

    def _get_intelligence(self):
        if not self._memory_intel:
            try:
                from core.memory.unified_memory import get_unified_memory
                self._memory_intel = get_unified_memory().get_memory_intelligence()
            except Exception as exc:  # noqa: BLE001
                logger.debug("memory intelligence lookup failed: %s", exc)
        if not self._data_arch:
            try:
                from core.data.architecture import get_data_architecture
                self._data_arch = get_data_architecture()
            except Exception as exc:
                logger.debug("LearningLoop data_arch init failed: %s", exc)
        return self._memory_intel

    def learn(self, category: str, input_data: dict, action: str,
              result: dict, metrics: dict | None = None) -> dict[str, Any]:
        """Full learning cycle from one execution.

        Args:
            category: What type of action (pricing, product, marketing)
            input_data: What data went in
            action: What was done
            result: What happened
            metrics: Business metrics (profit, conversion, cost, time)
        """
        mem = self._get_memory()
        mi = self._get_intelligence()
        metrics = metrics or {}

        # Step 1: EVALUATE
        score = self._evaluate(result, metrics)

        # Step 2: RECORD in IntelligentMemory (L3)
        tags = self._build_tags(category, action, score)
        mem.record_decision(
            category=category,
            input_data=input_data,
            action=action,
            result=result,
            score=score,
            tags=tags,
        )

        # Step 2b: RECORD in MemoryIntelligence (4-level, with promotion)
        if mi:
            mi.create_from_decision(
                category=category,
                input_data=input_data,
                action=action,
                result=result,
                score=score,
                tags=tags,
            )

        # Step 2c: RECORD in DataArchitecture (action→result tracking)
        if self._data_arch:
            action_id = f"ll_{category}_{int(time.time())}"
            self._data_arch.record_action(action_id, action, input_data)
            self._data_arch.attach_result(action_id, result, score=score)

        # Step 3: FAILURE ANALYSIS (both systems)
        failure_insight = None
        if score <= 2:
            failure_insight = self._analyze_failure(category, input_data, action, result, metrics)

        # Step 4: SUCCESS REINFORCEMENT
        success_insight = None
        if score >= 4:
            success_insight = self._reinforce_success(category, input_data, action, metrics)

        self._total_learnings += 1
        learning_result = {
            "score": score,
            "success": score >= 3,
            "failure_insight": failure_insight,
            "success_insight": success_insight,
            "total_learnings": self._total_learnings,
        }

        logger.info("Learning [%s/%s]: score=%.1f %s",
                    category, action, score, "SUCCESS" if score >= 3 else "FAILURE")
        return learning_result

    # ── Evaluation ───────────────────────────────────────────

    def _evaluate(self, result: dict, metrics: dict) -> float:
        """Evaluate execution result → score 1-5."""
        score = 3.0  # Neutral

        # Success/failure
        if result.get("status") in ("success", "executed", "completed"):
            score += 1.0
        elif result.get("status") in ("error", "failed"):
            score -= 1.5

        # Business metrics
        profit = float(metrics.get("profit", 0))
        if profit > 0:
            score += min(1.0, profit / 100)
        elif profit < 0:
            score -= min(1.0, abs(profit) / 100)

        conversion = float(metrics.get("conversion", 0))
        if conversion > 0.05:
            score += 0.5

        return max(1.0, min(5.0, round(score, 1)))

    # ── Failure Analysis ─────────────────────────────────────

    def _analyze_failure(self, category: str, input_data: dict, action: str,
                        result: dict, metrics: dict) -> dict[str, Any]:
        """Analyze why something failed — extract lessons."""
        mem = self._get_memory()

        # Find similar past failures
        context = mem.retrieve_for_decision(category, input_data)
        past_failures = context.get("failures", [])

        # Root cause analysis
        root_cause = "unknown"
        error = result.get("error", "")

        if "not found" in str(error).lower():
            root_cause = "missing_resource"
        elif "timeout" in str(error).lower():
            root_cause = "performance"
        elif "permission" in str(error).lower() or "403" in str(error):
            root_cause = "access_denied"
        elif metrics.get("profit", 0) < 0:
            root_cause = "unprofitable"
        elif metrics.get("conversion", 0) == 0:
            root_cause = "no_conversion"

        # Is this a repeated failure?
        similar_failures = sum(1 for f in past_failures if f.get("action") == action)
        is_repeated = similar_failures >= 2

        # Store as bad data for future reference
        mem._store_bad_data(category, {
            "action": action, "input_summary": str(input_data)[:200],
            "error": str(error)[:200], "root_cause": root_cause,
        }, f"Failure: {root_cause}")

        # Record in MemoryIntelligence failure tracking (auto-generates avoidance rules)
        mi = self._get_intelligence()
        if mi:
            mi.record_failure(
                category=category,
                failure_data={"action": action, "error": str(error)[:200],
                              "metrics": metrics},
                root_cause=root_cause,
                severity="critical" if similar_failures >= 2 else "medium",
            )

        insight = {
            "root_cause": root_cause,
            "is_repeated": is_repeated,
            "times_failed": similar_failures + 1,
            "recommendation": self._failure_recommendation(root_cause, is_repeated),
        }

        logger.warning("Failure analysis [%s/%s]: %s (repeated: %s)",
                       category, action, root_cause, is_repeated)
        return insight

    @staticmethod
    def _failure_recommendation(root_cause: str, is_repeated: bool) -> str:
        if is_repeated:
            return f"STOP using this approach — repeated failure ({root_cause})"

        recs = {
            "missing_resource": "Check data availability before acting",
            "performance": "Reduce scope or increase timeout",
            "access_denied": "Check API permissions",
            "unprofitable": "Review pricing and cost structure",
            "no_conversion": "Test different approach or audience",
        }
        return recs.get(root_cause, f"Investigate root cause: {root_cause}")

    # ── Success Reinforcement ────────────────────────────────

    def _reinforce_success(self, category: str, input_data: dict,
                          action: str, metrics: dict) -> dict[str, Any]:
        """Reinforce successful patterns — do more of what works."""
        features = self._get_memory()._extract_features(category, input_data)

        insight = {
            "action": action,
            "key_features": features,
            "recommendation": f"Continue {action} — proven successful",
            "metrics": metrics,
        }

        logger.info("Success reinforced [%s/%s]: %s", category, action, features)
        return insight

    @staticmethod
    def _build_tags(category: str, action: str, score: float) -> list[str]:
        tags = [category, action]
        if score >= 4:
            tags.append("success")
        elif score <= 2:
            tags.append("failure")
        return tags

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_learnings": self._total_learnings,
            "memory": self._get_memory().get_stats(),
        }
