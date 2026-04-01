"""BaseAgent — бүх agent-ийн суурь contract.

Agent бол engine биш.
Agent бол олон engine-ийг ашиглан зорилгод хүрэхийн тулд
дараалсан decision гаргадаг system unit.

Agent contract:
  Input:  {goal, context, constraints}
  Output: {status, data, meta: {agent, steps, engines_used}, error}

Agent дотор:
  1. Planning — ямар engine хэрэгтэйг шийднэ
  2. Execution — engine-үүдийг дараалал руу ажиллуулна
  3. Evaluation — result-ийг үнэлнэ
  4. Learning — дараагийн удаад сайжруулна
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Abstract base class for all ShopAI agents.

    Every agent MUST implement:
      - plan(goal, context) → execution plan
      - execute(plan, context) → results
      - evaluate(results) → quality assessment

    Agent MUST NOT:
      - Execute logic directly (use engines)
      - Call other agents directly (orchestrator does that)
      - Modify system structure
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._history: list[dict[str, Any]] = []
        self._step_log: list[dict[str, Any]] = []

    def run(self, goal: str, context: dict[str, Any] | None = None, constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the agent — plan → execute → evaluate → learn.

        This is the ONLY public method. It orchestrates the full cycle.
        """
        start = time.monotonic()
        ctx = context or {}
        cons = constraints or {}
        self._step_log = []

        try:
            # Step 1: Plan — decide which engines to use and in what order
            self._log_step("planning", "started")
            plan = self.plan(goal, ctx, cons)
            self._log_step("planning", "completed", {"engines": plan.get("engines", [])})

            if not plan.get("engines"):
                return self._output("fail", None, "Planning produced no engine steps", start)

            # Step 2: Execute — run engines in sequence
            self._log_step("execution", "started")
            results = self.execute(plan, ctx)
            self._log_step("execution", "completed", {"results_count": len(results.get("engine_results", {}))})

            # Step 3: Evaluate — assess quality of results
            self._log_step("evaluation", "started")
            evaluation = self.evaluate(results, goal)
            self._log_step("evaluation", "completed", {"score": evaluation.get("score", 0)})

            # Step 4: Learn — store experience for next time
            self._log_step("learning", "started")
            learning = self.learn(goal, plan, results, evaluation)
            self._log_step("learning", "completed")

            # Build final output
            output_data = {
                "goal": goal,
                "plan": plan,
                "results": results,
                "evaluation": evaluation,
                "learning": learning,
                "recommendation": self.recommend(results, evaluation),
            }

            return self._output("success", output_data, None, start)

        except Exception as exc:
            self._log_step("error", str(exc))
            return self._output("fail", None, str(exc), start)

    @abstractmethod
    def plan(self, goal: str, context: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        """Plan which engines to use and in what order.

        Returns:
            {
                "engines": [{"name": str, "purpose": str, "input": dict}, ...],
                "strategy": str,
                "estimated_steps": int,
            }
        """
        ...

    @abstractmethod
    def execute(self, plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Execute the plan by calling engines in sequence.

        Returns:
            {
                "engine_results": {engine_name: result_dict, ...},
                "completed_steps": int,
                "failed_steps": int,
            }
        """
        ...

    @abstractmethod
    def evaluate(self, results: dict[str, Any], goal: str) -> dict[str, Any]:
        """Evaluate the quality of results.

        Returns:
            {
                "score": 0-100,
                "quality": "high" | "medium" | "low",
                "issues": [...],
                "strengths": [...],
            }
        """
        ...

    def learn(self, goal: str, plan: dict[str, Any], results: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Learn from this execution for future improvement. Override to customize."""
        entry = {
            "goal": goal,
            "engines_used": [e["name"] for e in plan.get("engines", [])],
            "score": evaluation.get("score", 0),
            "success": evaluation.get("score", 0) >= 50,
            "timestamp": time.time(),
        }
        self._history.append(entry)

        # Keep last 100 entries
        if len(self._history) > 100:
            self._history = self._history[-100:]

        return {
            "recorded": True,
            "total_history": len(self._history),
            "avg_score": round(sum(h["score"] for h in self._history) / len(self._history), 1) if self._history else 0,
        }

    def recommend(self, results: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Generate recommendation based on results. Override to customize."""
        score = evaluation.get("score", 0)
        if score >= 70:
            return {"action": "proceed", "confidence": "high", "reason": "Results are strong"}
        if score >= 40:
            return {"action": "review", "confidence": "medium", "reason": "Results need human review"}
        return {"action": "retry_or_skip", "confidence": "low", "reason": "Results are weak — consider different approach"}

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get execution history."""
        return self._history[-limit:]

    def get_success_rate(self) -> float:
        """Get historical success rate."""
        if not self._history:
            return 0.0
        return round(sum(1 for h in self._history if h["success"]) / len(self._history) * 100, 1)

    def _log_step(self, step: str, status: str, details: dict[str, Any] | None = None) -> None:
        self._step_log.append({
            "step": step,
            "status": status,
            "details": details or {},
            "timestamp": time.time(),
        })

    def _output(self, status: str, data: Any, error: str | None, start: float) -> dict[str, Any]:
        elapsed = time.monotonic() - start
        return {
            "status": status,
            "data": data,
            "meta": {
                "agent": self.name,
                "steps": self._step_log,
                "engines_used": [s["details"].get("engines", []) for s in self._step_log if s.get("details", {}).get("engines")],
                "elapsed_seconds": round(elapsed, 3),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "error": {"reason": error} if error else None,
        }
