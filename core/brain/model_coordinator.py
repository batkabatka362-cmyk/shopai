"""ModelCoordinator — orchestrates 3 worker models + 1 learning model.

Worker models (execution, real-time):
  Mistral  → Analyzer (evaluate, score, decide)
  Qwen     → Worker (calculate, process, execute)
  LLaMA    → Creative (generate content, descriptions, copy)

Learning model (offline, parallel):
  Mistral  → Intelligence (analyze data, find patterns, generate rules)

Workers and learner run in PARALLEL. Learning never blocks execution.
Data is SEPARATED: live data vs historical data vs test data.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.coordinator")


class ModelCoordinator:
    """Coordinates all AI models — workers execute, learner improves."""

    def __init__(self) -> None:
        self._llm = None
        self._learning_thread: threading.Thread | None = None
        self._learning_running = False
        self._execution_log: list[dict] = []
        self._learning_results: list[dict] = []

    def _get_llm(self):
        if not self._llm:
            from core.system.llm_adapter import get_llm
            self._llm = get_llm()
        return self._llm

    # ── Worker Models (real-time execution) ──────────────────

    def analyze(self, prompt: str, context: dict | None = None) -> dict[str, Any]:
        """Mistral: analyze data, evaluate, score, decide."""
        llm = self._get_llm()
        response = llm.ask("analyzer", prompt, context)
        result = {
            "role": "analyzer", "model": response.model,
            "success": response.success, "duration_s": response.duration_s,
            "output": response.parse_json() if response.success else {"error": response.error},
        }
        self._log_execution("analyze", result)
        return result

    def execute(self, prompt: str, context: dict | None = None) -> dict[str, Any]:
        """Qwen: calculate, process, execute tasks."""
        llm = self._get_llm()
        response = llm.ask("worker", prompt, context)
        result = {
            "role": "worker", "model": response.model,
            "success": response.success, "duration_s": response.duration_s,
            "output": response.parse_json() if response.success else {"error": response.error},
        }
        self._log_execution("execute", result)
        return result

    def create(self, prompt: str, context: dict | None = None) -> dict[str, Any]:
        """LLaMA: generate content, descriptions, creative copy."""
        llm = self._get_llm()
        response = llm.ask("creative", prompt, context)
        result = {
            "role": "creative", "model": response.model,
            "success": response.success, "duration_s": response.duration_s,
            "output": response.text if response.success else response.error,
        }
        self._log_execution("create", result)
        return result

    def ask_all(self, prompt: str, context: dict | None = None) -> dict[str, Any]:
        """Ask all 3 workers the same question, return all answers."""
        results = {}
        for role, method in [("analyzer", self.analyze), ("worker", self.execute), ("creative", self.create)]:
            results[role] = method(prompt, context)
        return results

    # ── Learning Model (parallel, offline) ───────────────────

    def start_learning(self, data: dict[str, Any]) -> dict[str, Any]:
        """Start learning model in background — never blocks execution."""
        if self._learning_running:
            return {"status": "already_running"}

        self._learning_running = True
        self._learning_thread = threading.Thread(
            target=self._learning_cycle, args=(data,),
            daemon=True, name="shopai-learning-model",
        )
        self._learning_thread.start()
        return {"status": "started"}

    def _learning_cycle(self, data: dict[str, Any]) -> None:
        """Learning model cycle — runs in background."""
        try:
            start = time.monotonic()
            from core.brain.learning_model import LearningModel
            learner = LearningModel()

            # Phase 1: Analyze historical data
            analysis = learner.analyze_data(data)

            # Phase 2: Find patterns
            patterns = learner.find_patterns(data)

            # Phase 3: Generate rules
            rules = learner.generate_rules(patterns)

            # Phase 4: Test strategies (simulation)
            simulations = learner.simulate_strategies(data)

            elapsed = time.monotonic() - start
            result = {
                "status": "complete",
                "duration_s": round(elapsed, 2),
                "analysis": analysis,
                "patterns_found": len(patterns),
                "rules_generated": len(rules),
                "simulations_run": len(simulations),
                "timestamp": time.time(),
            }
            self._learning_results.append(result)
            logger.info("Learning cycle complete: %d patterns, %d rules (%.1fs)",
                       len(patterns), len(rules), elapsed)

        except Exception as exc:
            logger.error("Learning cycle failed: %s", exc)
            self._learning_results.append({"status": "failed", "error": str(exc)})
        finally:
            self._learning_running = False

    def get_learning_results(self, limit: int = 5) -> list[dict]:
        return self._learning_results[-limit:]

    # ── Coordinated Operations ───────────────────────────────

    def product_analysis(self, product: dict) -> dict[str, Any]:
        """Full product analysis using all models coordinately."""
        name = product.get("name", product.get("title", ""))
        price = product.get("price", 0)
        cost = product.get("cost", 0)
        # Business model comes from the product payload when the
        # caller supplies it; defaults to the legacy phrasing for
        # backward compat with all existing callers.
        model_label = (
            product.get("business_model") or "dropshipping"
        )

        # Analyzer: evaluate product potential
        analysis = self.analyze(
            f"Evaluate this product for {model_label}. Score 1-10. Product: {name}, Price: ${price}, Cost: ${cost}. Reply JSON: {{\"score\": N, \"verdict\": \"buy/skip\", \"reason\": \"...\"}}",
            product,
        )

        # Worker: calculate optimal metrics
        metrics = self.execute(
            f"Calculate: margin, ROI, break-even for product. Price: ${price}, Cost: ${cost}. Reply JSON: {{\"margin_pct\": N, \"roi_pct\": N, \"break_even_units\": N}}",
            product,
        )

        # Creative: generate description
        content = self.create(
            f"Write a 2-sentence product description for: {name}. Make it compelling for online shoppers.",
        )

        return {
            "product": name,
            "analysis": analysis.get("output", {}),
            "metrics": metrics.get("output", {}),
            "description": content.get("output", ""),
            "models_used": 3,
        }

    def pricing_decision(self, product: dict, market_data: dict | None = None) -> dict[str, Any]:
        """Coordinated pricing decision."""
        name = product.get("name", "")
        price = product.get("price", 0)
        cost = product.get("cost", 0)
        from utils.finance import margin as _margin
        margin = _margin(price, cost)

        result = self.analyze(
            f"Pricing decision for {name}. Current: ${price}, Cost: ${cost}, Margin: {margin:.0%}. "
            f"Should I raise, lower, or keep price? Consider: 0 orders so far, no competitor data. "
            f"Reply JSON: {{\"action\": \"raise/lower/keep\", \"new_price\": N, \"reason\": \"...\"}}",
            {"product": product, "market": market_data or {}},
        )

        return {
            "product": name,
            "current_price": price,
            "decision": result.get("output", {}),
            "model": result.get("model", ""),
        }

    # ── Stats ────────────────────────────────────────────────

    def _log_execution(self, operation: str, result: dict) -> None:
        self._execution_log.append({
            "operation": operation,
            "role": result.get("role", ""),
            "success": result.get("success", False),
            "duration_s": result.get("duration_s", 0),
            "timestamp": time.time(),
        })
        if len(self._execution_log) > 500:
            self._execution_log = self._execution_log[-500:]

    def get_stats(self) -> dict[str, Any]:
        total = len(self._execution_log)
        by_role: dict[str, int] = {}
        by_op: dict[str, int] = {}
        for e in self._execution_log:
            by_role[e["role"]] = by_role.get(e["role"], 0) + 1
            by_op[e["operation"]] = by_op.get(e["operation"], 0) + 1

        return {
            "total_executions": total,
            "by_role": by_role,
            "by_operation": by_op,
            "learning_running": self._learning_running,
            "learning_results": len(self._learning_results),
        }
