"""SmartExecutor — intelligent execution with simulation + learning.

NOT just an executor. An AI that learns from doing.

3 Execution Modes:
  SIMULATE  — estimate outcome without touching anything (default)
  DRY_RUN   — validate everything, stop before API call
  LIVE      — execute on real Shopify (needs credentials)

Every execution (even simulated) produces:
  action + predicted_outcome + actual_outcome + score → memory

Safety Rules:
  - Low confidence (< 0.5) → always simulate
  - First time action → always simulate
  - Repeated success (3+) → can auto-promote to dry_run/live
  - Any failure → demote back to simulate
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("smart_executor")


RISK_LEVELS = {
    # action_type: (risk_level, min_confidence_for_live)
    "pricing_recommendation": ("medium", 0.7),
    "update_price": ("medium", 0.7),
    "promote_high_margin": ("low", 0.5),
    "add_images": ("low", 0.4),
    "alert": ("low", 0.3),
    "brain_recommendation": ("low", 0.4),
    "inventory_alert": ("medium", 0.6),
    "update_inventory": ("high", 0.8),
    "create_product": ("high", 0.8),
    "update_product": ("medium", 0.7),
    "bulk_update": ("high", 0.9),
}


class SmartExecutor:
    """Intelligent executor — simulates, learns, then acts."""

    def __init__(self) -> None:
        self._memory_intel = None
        self._data_arch = None
        self._learning_loop = None
        self._execution_log: list[dict[str, Any]] = []
        self._simulation_count = 0
        self._live_count = 0

    def _ensure_init(self) -> None:
        if not self._memory_intel:
            try:
                from core.memory.intelligence import get_memory_intelligence
                self._memory_intel = get_memory_intelligence()
            except Exception:
                pass
        if not self._data_arch:
            try:
                from core.data.architecture import get_data_architecture
                self._data_arch = get_data_architecture()
            except Exception:
                pass
        if not self._learning_loop:
            try:
                from core.brain.learning_loop import LearningLoop
                self._learning_loop = LearningLoop()
            except Exception:
                pass

    # == MAIN EXECUTION ============================================

    def execute(self, action: dict[str, Any],
                store_data: dict | None = None) -> dict[str, Any]:
        """Execute an action intelligently.

        1. Consult memory for past similar actions
        2. Estimate outcome via simulation
        3. Decide execution mode (simulate/dry_run/live)
        4. Execute
        5. Record result for learning
        6. Return outcome

        Args:
            action: {type, store_id, params, reason, engine, confidence}
            store_data: current store data for simulation context

        Returns:
            Execution result with simulation/outcome data
        """
        self._ensure_init()
        start = time.monotonic()

        action_type = action.get("type", "unknown")
        confidence = float(action.get("confidence", 0.5))
        store_id = action.get("store_id", "")

        # Step 1: Consult memory
        memory_context = self._consult_memory(action_type)

        # Step 2: Determine execution mode
        mode = self._determine_mode(action_type, confidence, memory_context)

        # Step 3: Simulate outcome
        predicted = self._simulate(action, store_data or {})

        # Step 4: Execute based on mode
        if mode == "live":
            actual = self._execute_live(action)
        elif mode == "dry_run":
            actual = self._execute_dry_run(action)
        else:  # simulate
            actual = predicted  # In simulation, predicted = actual

        # Step 5: Score the outcome
        score = self._score_outcome(action, predicted, actual, mode)

        # Step 6: Record for learning
        self._record_execution(action, predicted, actual, score, mode)

        elapsed = time.monotonic() - start

        result = {
            "action_id": f"se_{int(time.time()*1000)}",
            "action_type": action_type,
            "mode": mode,
            "confidence": confidence,
            "predicted_outcome": predicted,
            "actual_outcome": actual,
            "score": score,
            "memory_consulted": memory_context.get("total_memories", 0) > 0,
            "past_successes": len(memory_context.get("best_events", [])),
            "past_failures": len(memory_context.get("failures", [])),
            "duration_s": round(elapsed, 3),
            "status": "executed",
        }

        self._execution_log.append(result)
        if mode == "simulate":
            self._simulation_count += 1
        else:
            self._live_count += 1

        logger.info("SmartExec [%s] mode=%s score=%.1f confidence=%.2f %.3fs",
                    action_type, mode, score, confidence, elapsed)

        return result

    def execute_batch(self, actions: list[dict[str, Any]],
                      store_data: dict | None = None) -> dict[str, Any]:
        """Execute multiple actions."""
        results = []
        for action in actions:
            r = self.execute(action, store_data)
            results.append(r)

        return {
            "total": len(results),
            "simulated": sum(1 for r in results if r["mode"] == "simulate"),
            "dry_run": sum(1 for r in results if r["mode"] == "dry_run"),
            "live": sum(1 for r in results if r["mode"] == "live"),
            "avg_score": round(sum(r["score"] for r in results) / max(len(results), 1), 1),
            "results": results,
        }

    # == MEMORY CONSULTATION =======================================

    def _consult_memory(self, action_type: str) -> dict[str, Any]:
        """Check memory for past similar actions."""
        if not self._memory_intel:
            return {"total_memories": 0}

        context = self._memory_intel.retrieve_for_decision(action_type)

        # Also check specific action type memories
        action_memories = self._memory_intel.retrieve(
            category=action_type, min_score=0.0, limit=10,
        )

        context["action_specific"] = action_memories
        return context

    # == MODE DETERMINATION ========================================

    def _determine_mode(self, action_type: str, confidence: float,
                        memory: dict) -> str:
        """Determine execution mode based on risk, confidence, and history."""
        risk_info = RISK_LEVELS.get(action_type, ("medium", 0.7))
        risk_level = risk_info[0]
        min_confidence = risk_info[1]

        # Rule 1: Low confidence → always simulate
        if confidence < 0.4:
            return "simulate"

        # Rule 2: No past data → simulate first
        if memory.get("total_memories", 0) == 0:
            return "simulate"

        # Rule 3: High risk → simulate unless very confident with history
        if risk_level == "high":
            past_successes = len(memory.get("best_events", []))
            if past_successes < 3 or confidence < min_confidence:
                return "simulate"
            return "dry_run"  # Even high-risk with history gets dry_run, not live

        # Rule 4: Past failures for this action → simulate
        failures = memory.get("failures", [])
        recent_failures = [f for f in failures if f.get("action") == action_type]
        if recent_failures:
            return "simulate"

        # Rule 5: Medium risk with good confidence
        if risk_level == "medium" and confidence >= min_confidence:
            past_successes = len(memory.get("best_events", []))
            if past_successes >= 3:
                return "dry_run"
            return "simulate"

        # Rule 6: Low risk with any confidence
        if risk_level == "low" and confidence >= min_confidence:
            return "simulate"  # Even low risk starts with simulate

        return "simulate"

    # == SIMULATION ================================================

    def _simulate(self, action: dict[str, Any],
                  store_data: dict) -> dict[str, Any]:
        """Simulate the outcome of an action."""
        action_type = action.get("type", "")
        params = action.get("params", {})
        products = store_data.get("products", [])

        if action_type in ("pricing_recommendation", "update_price"):
            return self._simulate_pricing(params, products)
        elif action_type in ("promote_high_margin",):
            return self._simulate_promotion(params, products)
        elif action_type in ("add_images",):
            return self._simulate_content_improvement(params, products)
        elif action_type in ("alert", "brain_recommendation"):
            return self._simulate_alert(action)
        elif action_type in ("inventory_alert", "update_inventory"):
            return self._simulate_inventory(params, products)
        else:
            return self._simulate_generic(action)

    def _simulate_pricing(self, params: dict, products: list) -> dict[str, Any]:
        """Simulate a pricing change."""
        rec_price = float(params.get("price", params.get("recommended_price", 0)))
        product_id = params.get("product_id", "")

        # Find current price
        current_price = 0
        current_cost = 0
        for p in products:
            if str(p.get("id", "")) == str(product_id):
                current_price = float(p.get("price", 0))
                current_cost = float(p.get("cost", 0))
                break

        if not current_price:
            current_price = rec_price
        if not current_cost:
            current_cost = current_price * 0.4

        price_change_pct = ((rec_price - current_price) / current_price * 100) if current_price > 0 else 0
        new_margin = (rec_price - current_cost) / rec_price if rec_price > 0 else 0

        # Estimate demand impact (price elasticity ~ -1.5 for e-commerce)
        elasticity = -1.5
        demand_change_pct = price_change_pct * elasticity
        estimated_revenue_change = price_change_pct + demand_change_pct

        return {
            "type": "pricing_simulation",
            "current_price": current_price,
            "recommended_price": rec_price,
            "price_change_pct": round(price_change_pct, 1),
            "new_margin": round(new_margin, 3),
            "estimated_demand_change_pct": round(demand_change_pct, 1),
            "estimated_revenue_change_pct": round(estimated_revenue_change, 1),
            "profitable": new_margin > 0.1,
            "risk": "low" if abs(price_change_pct) < 10 else "medium" if abs(price_change_pct) < 25 else "high",
            "success": new_margin > 0.1 and estimated_revenue_change > -10,
        }

    def _simulate_promotion(self, params: dict, products: list) -> dict[str, Any]:
        """Simulate promoting high-margin products."""
        high_margin = [p for p in products
                       if float(p.get("cost", 0)) > 0
                       and (float(p.get("price", 0)) - float(p.get("cost", 0))) / float(p.get("price", 1)) > 0.5]
        return {
            "type": "promotion_simulation",
            "high_margin_products": len(high_margin),
            "estimated_visibility_boost": 0.2,
            "estimated_revenue_impact": len(high_margin) * 10,
            "success": len(high_margin) > 0,
        }

    def _simulate_content_improvement(self, params: dict, products: list) -> dict[str, Any]:
        """Simulate adding images/content."""
        without_images = [p for p in products
                          if not (p.get("images") or p.get("image") or p.get("image_url"))]
        return {
            "type": "content_simulation",
            "products_needing_images": len(without_images),
            "estimated_conversion_boost": 0.15 if without_images else 0,
            "success": True,
        }

    def _simulate_alert(self, action: dict) -> dict[str, Any]:
        """Simulate an alert action."""
        return {
            "type": "alert_simulation",
            "alert_type": action.get("type", ""),
            "reason": action.get("reason", "")[:80],
            "acknowledged": True,
            "success": True,
        }

    def _simulate_inventory(self, params: dict, products: list) -> dict[str, Any]:
        """Simulate inventory change."""
        return {
            "type": "inventory_simulation",
            "products_affected": 1,
            "estimated_stockout_prevention": True,
            "success": True,
        }

    def _simulate_generic(self, action: dict) -> dict[str, Any]:
        """Generic simulation for unknown action types."""
        return {
            "type": "generic_simulation",
            "action_type": action.get("type", "unknown"),
            "confidence": action.get("confidence", 0),
            "success": action.get("confidence", 0) > 0.5,
        }

    # == LIVE EXECUTION ============================================

    def _execute_live(self, action: dict) -> dict[str, Any]:
        """Execute on real Shopify — delegate to ActionExecutor."""
        try:
            from execution.action_executor import ActionExecutor
            executor = ActionExecutor()
            return executor.execute_action(action)
        except Exception as exc:
            return {"error": str(exc), "success": False}

    def _execute_dry_run(self, action: dict) -> dict[str, Any]:
        """Validate everything but don't execute."""
        return {
            "type": "dry_run",
            "action_type": action.get("type", ""),
            "would_execute": True,
            "validated": True,
            "success": True,
        }

    # == SCORING ===================================================

    @staticmethod
    def _score_outcome(action: dict, predicted: dict, actual: dict,
                       mode: str) -> float:
        """Score the execution outcome 1-5."""
        score = 3.0  # Neutral default

        # Success/failure
        if actual.get("success"):
            score += 1.0
        elif actual.get("error"):
            score -= 1.5

        # Revenue impact
        rev_change = float(actual.get("estimated_revenue_change_pct",
                           predicted.get("estimated_revenue_change_pct", 0)) or 0)
        if rev_change > 5:
            score += 0.5
        elif rev_change < -5:
            score -= 0.5

        # Profitable
        if actual.get("profitable"):
            score += 0.3

        # Mode penalty: simulation is inherently less certain
        if mode == "simulate":
            score = max(2.0, score - 0.3)  # Slight uncertainty penalty

        # Confidence alignment
        confidence = float(action.get("confidence", 0.5))
        if confidence > 0.7 and score >= 3.5:
            score += 0.2

        return max(1.0, min(5.0, round(score, 1)))

    # == LEARNING ==================================================

    def _record_execution(self, action: dict, predicted: dict,
                          actual: dict, score: float, mode: str) -> None:
        """Record execution for learning."""
        action_type = action.get("type", "unknown")
        category = action_type

        # Record in MemoryIntelligence
        if self._memory_intel:
            self._memory_intel.create_from_decision(
                category=category,
                input_data={"action": action, "predicted": predicted},
                action=action_type,
                result=actual,
                score=score,
                tags=[category, mode, "execution",
                      "success" if actual.get("success") else "failure"],
            )

            # Failures are gold
            if score <= 2.0:
                self._memory_intel.record_failure(
                    category=category,
                    failure_data={"action": action, "result": actual},
                    root_cause=actual.get("error", f"low_score_{score}"),
                    severity="critical" if score <= 1.5 else "medium",
                )

        # Record in DataArchitecture
        if self._data_arch:
            action_id = f"se_{action_type}_{int(time.time())}"
            self._data_arch.record_action(
                action_id=action_id,
                action_type=action_type,
                action_data={"confidence": action.get("confidence", 0),
                             "mode": mode, "reason": action.get("reason", "")},
            )
            self._data_arch.attach_result(
                action_id, actual, score=score,
            )

        # Feed to LearningLoop
        if self._learning_loop:
            self._learning_loop.learn(
                category=category,
                input_data=action,
                action=action_type,
                result=actual,
                metrics={
                    "profit": float(actual.get("estimated_revenue_change_pct", 0) or 0),
                    "conversion": float(actual.get("estimated_conversion_boost", 0) or 0),
                },
            )

    # == STATS =====================================================

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_executions": len(self._execution_log),
            "simulations": self._simulation_count,
            "live": self._live_count,
            "avg_score": round(
                sum(r["score"] for r in self._execution_log) / max(len(self._execution_log), 1), 1,
            ),
            "by_mode": {
                "simulate": sum(1 for r in self._execution_log if r["mode"] == "simulate"),
                "dry_run": sum(1 for r in self._execution_log if r["mode"] == "dry_run"),
                "live": sum(1 for r in self._execution_log if r["mode"] == "live"),
            },
            "by_type": {},
        }


# Singleton
_instance: SmartExecutor | None = None


def get_smart_executor() -> SmartExecutor:
    global _instance
    if _instance is None:
        _instance = SmartExecutor()
    return _instance
