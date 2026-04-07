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

import threading
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
        # Lock guarding _history mutations. Multiple cycles can
        # call run() on the same agent instance concurrently
        # (AgentDispatcher dispatches to singleton agents), so
        # the unbounded list append + slice on _history needs to
        # be serialized.
        self._lock = threading.Lock()

    def run(self, goal: str, context: dict[str, Any] | None = None, constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the agent — plan → execute → evaluate → learn.

        This is the ONLY public method. It orchestrates the full cycle.
        """
        start = time.monotonic()
        ctx = context or {}
        cons = constraints or {}
        # CRITICAL: step_log MUST be local to this run() call.
        # The previous version stored it on the instance
        # (`self._step_log = []`) which made it shared mutable
        # state across concurrent run() invocations on the same
        # agent — two threads would interleave their step entries
        # and one thread's _output() would emit the OTHER
        # thread's steps in its meta.steps list. Local var
        # eliminates the race entirely.
        step_log: list[dict[str, Any]] = []

        try:
            # Step 1: Plan — decide which engines to use and in what order
            self._log_step(step_log, "planning", "started")
            plan = self.plan(goal, ctx, cons)
            if not isinstance(plan, dict):
                plan = {}
            self._log_step(
                step_log, "planning", "completed",
                {"engines": plan.get("engines", [])},
            )

            if not plan.get("engines"):
                return self._output(
                    "fail", None, "Planning produced no engine steps",
                    start, step_log,
                )

            # Step 2: Execute — run engines in sequence
            self._log_step(step_log, "execution", "started")
            results = self.execute(plan, ctx)
            if not isinstance(results, dict):
                results = {}
            engine_results = results.get("engine_results") or {}
            self._log_step(
                step_log, "execution", "completed",
                {"results_count": len(engine_results)},
            )

            # Step 3: Evaluate — assess quality of results
            self._log_step(step_log, "evaluation", "started")
            evaluation = self.evaluate(results, goal)
            if not isinstance(evaluation, dict):
                evaluation = {}
            self._log_step(
                step_log, "evaluation", "completed",
                {"score": evaluation.get("score", 0)},
            )

            # Step 4: Learn — store experience for next time
            self._log_step(step_log, "learning", "started")
            learning = self.learn(goal, plan, results, evaluation)
            self._log_step(step_log, "learning", "completed")

            # Build final output
            output_data = {
                "goal": goal,
                "plan": plan,
                "results": results,
                "evaluation": evaluation,
                "learning": learning,
                "recommendation": self.recommend(results, evaluation),
            }

            return self._output("success", output_data, None, start, step_log)

        except Exception as exc:  # noqa: BLE001
            # Capture both the exception type AND its message so the
            # operator can tell a TypeError apart from a RuntimeError
            # in the audit trail. Previously only str(exc) was kept.
            err_msg = f"{type(exc).__name__}: {exc}"
            self._log_step(step_log, "error", err_msg)
            return self._output("fail", None, err_msg, start, step_log)

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
        # Defensive .get on each engine entry — a future plan that
        # forgets to populate "name" can't crash the entire learn
        # phase with KeyError.
        engines_used = [
            e.get("name", "unknown")
            for e in (plan.get("engines") or [])
            if isinstance(e, dict)
        ]
        score = (evaluation or {}).get("score", 0) if isinstance(evaluation, dict) else 0
        entry = {
            "goal": goal,
            "engines_used": engines_used,
            "score": score,
            "success": score >= 50,
            "timestamp": time.time(),
        }
        with self._lock:
            self._history.append(entry)
            # Keep last 100 entries
            if len(self._history) > 100:
                self._history = self._history[-100:]
            avg_score = (
                round(sum(h["score"] for h in self._history) / len(self._history), 1)
                if self._history else 0
            )
            total_history = len(self._history)

        return {
            "recorded": True,
            "total_history": total_history,
            "avg_score": avg_score,
        }

    def recommend(self, results: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Generate recommendation based on results. Override to customize."""
        score = (evaluation or {}).get("score", 0) if isinstance(evaluation, dict) else 0
        if score >= 70:
            return {"action": "proceed", "confidence": "high", "reason": "Results are strong"}
        if score >= 40:
            return {"action": "review", "confidence": "medium", "reason": "Results need human review"}
        return {"action": "retry_or_skip", "confidence": "low", "reason": "Results are weak — consider different approach"}

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get execution history.

        Returns defensive copies so caller mutation can't poison
        the in-memory history. Same defensive-copy pattern from
        audit passes 12 / 17 / 18 / 19 / 22 / 23.
        """
        with self._lock:
            return [dict(h) for h in self._history[-limit:]]

    def get_success_rate(self) -> float:
        """Get historical success rate."""
        with self._lock:
            if not self._history:
                return 0.0
            return round(
                sum(1 for h in self._history if h.get("success")) / len(self._history) * 100,
                1,
            )

    @staticmethod
    def _log_step(
        step_log: list[dict[str, Any]],
        step: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append a step entry to the per-run step_log.

        Static so it can't accidentally read or write instance
        state — every call must explicitly pass the local
        step_log list, ruling out the instance-state race that
        the previous version had.
        """
        step_log.append({
            "step": step,
            "status": status,
            "details": details or {},
            "timestamp": time.time(),
        })

    def _output(
        self,
        status: str,
        data: Any,
        error: str | None,
        start: float,
        step_log: list[dict[str, Any]],
    ) -> dict[str, Any]:
        elapsed = time.monotonic() - start
        engines_used: list = []
        for s in step_log:
            details = s.get("details") if isinstance(s, dict) else None
            if isinstance(details, dict):
                engines = details.get("engines")
                if engines:
                    engines_used.append(engines)
        return {
            "status": status,
            "data": data,
            "meta": {
                "agent": self.name,
                "steps": list(step_log),
                "engines_used": engines_used,
                "elapsed_seconds": round(elapsed, 3),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "error": {"reason": error} if error else None,
        }
