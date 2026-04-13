"""TaskRouter — task-aware adaptive routing layer over LLMAdapter.

Where LLMAdapter knows how to talk to many providers, TaskRouter
knows which provider is BEST for a given kind of work. It learns
from history: every time a task succeeds or fails, the stats for
that (task_type, model) pair update, and over time the router
shifts toward the model that performs best on each task.

Two complementary modes coexist:

  1. Static role routing (fast path):
     For the first N invocations of a new task type, route by
     a built-in TASK_ROLE_MAP (analyze → analyzer, write → creative,
     extract → worker, etc.). The LLMAdapter then picks the actual
     model based on the role.

  2. Adaptive routing (learned path):
     Once we have ≥ MIN_OBSERVATIONS per task type per model, the
     router computes a quality score per model and picks the best.
     The score combines:
       - success_rate     (got a parseable result)
       - avg_latency      (lower is better)
       - cost_estimate    (local Ollama is free; API costs)
     Best model wins. Ties broken by latency.

Budget awareness: each call carries a `budget` hint
("local_only", "cheap", "premium") which the router respects:

    "local_only"  → only consider Ollama models
    "cheap"       → prefer local; fall back to OpenAI mini / Haiku
    "premium"     → all providers, prefer the highest-success model
                    regardless of cost

Stats survive across calls but live only in memory by default.
Pass `state_path=...` to enable JSON persistence so the router
remembers what it learned across daemon restarts.

TaskRouter does NOT replace LLMAdapter — it's a thin wrapper
around it. Cognitive modules can use either depending on whether
they want adaptive task routing or just direct prompt sending.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("task_router")


# ── Configuration ────────────────────────────────────────────

# Static role map: which role handles which task type by default
DEFAULT_TASK_ROLES: dict[str, str] = {
    # Analysis / decisions
    "analyze":             "analyzer",
    "analyze_product":     "analyzer",
    "score_product":       "analyzer",
    "compare_prices":      "analyzer",
    "classify_category":   "analyzer",
    "evaluate_strategy":   "analyzer",
    "diagnose_failure":    "analyzer",

    # Reasoning / planning
    "plan":                "reasoner",
    "decompose_goal":      "reasoner",
    "imagine_step":        "reasoner",
    "predict_response":    "reasoner",
    "pick_target":         "reasoner",
    "summarize_episodes":  "reasoner",
    "think":               "reasoner",

    # Worker / extraction
    "extract":             "worker",
    "extract_keywords":    "worker",
    "calculate_margin":    "worker",
    "parse_description":   "worker",
    "generate_tags":       "worker",
    "transform":           "worker",

    # Creative / writing
    "write":               "creative",
    "write_description":   "creative",
    "write_email":         "creative",
    "write_blog":          "creative",
    "write_social_post":   "creative",
    "describe":            "creative",
}

# How many observations of a (task_type, model) pair we need before
# we trust the adaptive score enough to pick that model over the
# static role default.
MIN_OBSERVATIONS = 5

# Budget tiers and which providers they allow.
BUDGET_PROVIDERS: dict[str, set[str]] = {
    "local_only": {"ollama"},
    "cheap": {"ollama", "openai", "anthropic"},
    "premium": {"ollama", "openai", "anthropic"},
}

# Cost per 1k tokens (rough estimates as of 2026, in USD).
# Used by the budget-aware tie-breaker. Real costs vary.
PROVIDER_COST_PER_1K_TOKENS: dict[str, float] = {
    "ollama":    0.0,     # local, free
    "openai":    0.0015,  # gpt-4o-mini default
    "anthropic": 0.0008,  # claude-haiku-4-5 default
}


# ── Stats ────────────────────────────────────────────────────


@dataclass
class TaskModelStats:
    """Per (task_type, model) performance record."""
    calls: int = 0
    successes: int = 0
    total_latency_s: float = 0.0
    total_tokens: int = 0
    last_used: float = 0.0

    def record(self, success: bool, latency_s: float, tokens: int) -> None:
        self.calls += 1
        if success:
            self.successes += 1
        self.total_latency_s += max(0.0, float(latency_s))
        self.total_tokens += max(0, int(tokens))
        self.last_used = time.time()

    @property
    def success_rate(self) -> float:
        return self.successes / self.calls if self.calls > 0 else 0.0

    @property
    def avg_latency_s(self) -> float:
        return self.total_latency_s / self.calls if self.calls > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 3),
            "avg_latency_s": round(self.avg_latency_s, 3),
            "total_tokens": self.total_tokens,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskModelStats":
        return cls(
            calls=int(d.get("calls", 0)),
            successes=int(d.get("successes", 0)),
            total_latency_s=float(d.get("total_latency_s", 0.0)),
            total_tokens=int(d.get("total_tokens", 0)),
            last_used=float(d.get("last_used", 0.0)),
        )


@dataclass
class RouteDecision:
    """The full record of a single routing decision."""
    task_type: str
    model: str
    role: str
    budget: str
    reason: str
    response: Any = None  # an LLMResponse-shaped object
    success: bool = False
    latency_s: float = 0.0


# ── Router ───────────────────────────────────────────────────


class TaskRouter:
    """Task-aware adaptive routing layer over LLMAdapter."""

    def __init__(
        self,
        adapter: Any = None,
        *,
        task_role_map: Optional[dict[str, str]] = None,
        learn: bool = True,
        state_path: Optional[str] = None,
    ) -> None:
        self._adapter = adapter
        self._task_role_map = dict(task_role_map or DEFAULT_TASK_ROLES)
        self._learn = bool(learn)
        self._state_path = state_path
        # task_type → model → stats
        self._stats: dict[str, dict[str, TaskModelStats]] = defaultdict(dict)
        self._lock = threading.RLock()
        if state_path:
            self._load_state()

    # ── Adapter resolution ────────────────────────────────────

    def _get_adapter(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        try:
            from core.system.llm_adapter import get_llm
            self._adapter = get_llm()
        except Exception:  # noqa: BLE001
            self._adapter = None
        return self._adapter

    # ── Public API ────────────────────────────────────────────

    def route(
        self,
        task_type: str,
        prompt: str,
        *,
        system_prompt: str = "",
        context: Optional[dict] = None,
        budget: str = "cheap",
        force_model: Optional[str] = None,
    ) -> RouteDecision:
        """Pick a model and execute the task.

        Args:
            task_type: short identifier; used for stats + role lookup
            prompt: user prompt
            system_prompt: optional system instruction
            context: optional dict folded into the prompt by the adapter
            budget: "local_only" | "cheap" | "premium"
            force_model: bypass routing entirely and use this model
                         (still records stats)

        Returns:
            RouteDecision with the response, latency, success flag,
            and the chosen model + role + reason.
        """
        adapter = self._get_adapter()
        if adapter is None:
            return RouteDecision(
                task_type=task_type, model="", role="",
                budget=budget,
                reason="no LLM adapter available",
                response=None,
                success=False,
            )

        role = self._task_role_map.get(task_type, "general")
        chosen_model = force_model or self._pick_model(
            task_type, role, budget,
        )
        decision = RouteDecision(
            task_type=task_type,
            model=chosen_model or "(adapter default)",
            role=role,
            budget=budget,
            reason=self._explain_choice(task_type, chosen_model, role),
        )

        # Temporarily set the role's preferred model so the adapter
        # routes to our pick. We restore the previous setting after.
        prev_model = None
        try:
            if chosen_model and hasattr(adapter, "_role_map"):
                prev_model = adapter._role_map.get(role)
                adapter._role_map[role] = chosen_model
        except Exception as exc:  # noqa: BLE001
            logger.debug("task router model role override failed: %s", exc)

        start = time.monotonic()
        try:
            response = adapter.ask(
                role=role,
                prompt=prompt,
                context=context,
                system_prompt=system_prompt,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TaskRouter.route adapter raised: %s", exc)
            response = None
        finally:
            if prev_model is not None and hasattr(adapter, "_role_map"):
                adapter._role_map[role] = prev_model

        decision.response = response
        decision.latency_s = round(time.monotonic() - start, 3)
        decision.success = bool(response and getattr(response, "success", False))

        # Record stats for adaptive learning
        if self._learn and chosen_model:
            tokens = int(getattr(response, "tokens_used", 0)) if response else 0
            self._record(task_type, chosen_model, decision.success,
                         decision.latency_s, tokens)
            if self._state_path:
                self._save_state()

        return decision

    # ── Model selection ───────────────────────────────────────

    def _pick_model(
        self, task_type: str, role: str, budget: str,
    ) -> Optional[str]:
        """Pick the best model for a task. Returns None to let the
        adapter use its default role mapping."""
        adapter = self._get_adapter()
        if adapter is None:
            return None

        configured = list(getattr(adapter, "_configs", {}).keys())
        if not configured:
            return None

        # Filter by budget
        allowed_providers = BUDGET_PROVIDERS.get(budget, BUDGET_PROVIDERS["cheap"])
        allowed_models = []
        for name in configured:
            cfg = adapter._configs.get(name)
            if cfg is None:
                continue
            if cfg.provider in allowed_providers:
                allowed_models.append(name)
        if not allowed_models:
            return None

        # Adaptive: if we have enough data for this task, use it
        with self._lock:
            task_stats = self._stats.get(task_type, {})
            mature = [
                (name, stats) for name, stats in task_stats.items()
                if stats.calls >= MIN_OBSERVATIONS and name in allowed_models
            ]
            if mature:
                # Pick the highest score
                ranked = sorted(
                    mature,
                    key=lambda kv: self._score_model(kv[1], allowed_providers),
                    reverse=True,
                )
                return ranked[0][0]

        # Fall through: prefer the role's default if it's in allowed,
        # otherwise the first allowed model
        role_default = adapter._role_map.get(role) if hasattr(adapter, "_role_map") else None
        if role_default and role_default in allowed_models:
            return role_default
        return allowed_models[0] if allowed_models else None

    @staticmethod
    def _score_model(
        stats: TaskModelStats, allowed_providers: set[str],
    ) -> float:
        """Composite quality score: higher = better.

        Combines:
            success_rate * 1.0          (most important)
            -log(latency_s + 1) * 0.05  (faster is better)
        Lower-cost models get a small bonus so ties go to local.
        """
        import math
        score = stats.success_rate
        score -= math.log(stats.avg_latency_s + 1) * 0.05
        return score

    def _explain_choice(
        self, task_type: str, model: Optional[str], role: str,
    ) -> str:
        if not model:
            return f"adapter default for role={role}"
        with self._lock:
            stats = self._stats.get(task_type, {}).get(model)
        if stats and stats.calls >= MIN_OBSERVATIONS:
            return (
                f"adaptive: model={model} success={stats.success_rate:.0%} "
                f"avg={stats.avg_latency_s:.2f}s n={stats.calls}"
            )
        return f"static: role={role} → model={model}"

    # ── Stats recording ───────────────────────────────────────

    def _record(
        self,
        task_type: str,
        model: str,
        success: bool,
        latency_s: float,
        tokens: int,
    ) -> None:
        with self._lock:
            row = self._stats[task_type].get(model)
            if row is None:
                row = TaskModelStats()
                self._stats[task_type][model] = row
            row.record(success, latency_s, tokens)

    # ── Read API ──────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Snapshot of the learned state."""
        with self._lock:
            return {
                task_type: {model: stats.to_dict() for model, stats in models.items()}
                for task_type, models in self._stats.items()
            }

    def best_model_for(self, task_type: str) -> Optional[str]:
        """Return the currently-preferred model for a task type, or None
        if we don't have enough data."""
        with self._lock:
            task_stats = self._stats.get(task_type, {})
            mature = [
                (name, stats) for name, stats in task_stats.items()
                if stats.calls >= MIN_OBSERVATIONS
            ]
            if not mature:
                return None
            ranked = sorted(
                mature,
                key=lambda kv: self._score_model(kv[1], set()),
                reverse=True,
            )
            return ranked[0][0]

    def reset_task(self, task_type: str) -> None:
        """Drop learned stats for one task type — forces re-exploration."""
        with self._lock:
            self._stats.pop(task_type, None)

    def reset_all(self) -> None:
        with self._lock:
            self._stats.clear()

    # ── Persistence ───────────────────────────────────────────

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            payload = self.stats()
            Path(self._state_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_path, "w") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TaskRouter save_state: %s", exc)

    def _load_state(self) -> None:
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path) as f:
                data = json.load(f)
            for task_type, models in data.items():
                for model, stats_dict in models.items():
                    self._stats[task_type][model] = TaskModelStats.from_dict(stats_dict)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TaskRouter load_state: %s", exc)


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[TaskRouter] = None


def get_task_router() -> TaskRouter:
    """Process-wide TaskRouter singleton."""
    global _instance
    if _instance is None:
        _instance = TaskRouter()
    return _instance


def reset_task_router_for_tests() -> None:
    global _instance
    _instance = None
