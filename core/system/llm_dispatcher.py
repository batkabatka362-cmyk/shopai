"""LLM dispatcher — route each query to the cheapest capable model.

ShopAI has three remote LLM providers (Groq, Gemini, DeepSeek)
plus Ollama for offline. Each has a different price, latency,
and capability profile. Call sites today hard-code a provider,
which means the daemon blows through the DeepSeek budget on
trivial classification queries while falling back to the
expensive path when Groq is down.

LLMDispatcher picks per request. Each registered model carries:

  • name               — e.g. "groq_llama3_70b"
  • capabilities       — set of tags the model can handle
                         {"classify", "summarise", "reason", "code"}
  • cost_per_1k_tokens — USD
  • typical_latency_s  — steady-state
  • max_tokens         — context limit
  • provider           — shared rate_limit / retry / budget namespace

dispatch(request) finds models whose capabilities include every
tag request requires, filters out those whose rate limiter /
circuit breaker / budget is exhausted, and returns the cheapest
survivor. Ties broken by lowest latency.

invoke(request, call_fn) wraps dispatch with execution + fallback:
if the top model fails (rate, circuit, exception), the next-
cheapest is tried. Records the outcome for trust_calibrator.

Pure orchestration — caller provides the actual LLM client fn.
Integrates with rate_limiter, retry_policy, trust_calibrator.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("system.llm_dispatcher")


@dataclass
class ModelSpec:
    name: str
    capabilities: frozenset[str]
    cost_per_1k_tokens: float
    typical_latency_s: float = 1.0
    max_tokens: int = 4096
    provider: str = ""                # maps to rate_limiter name

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "typical_latency_s": self.typical_latency_s,
            "max_tokens": self.max_tokens,
            "provider": self.provider,
        }


@dataclass
class Request:
    required_capabilities: frozenset[str]
    estimated_tokens: int = 500
    max_latency_s: float | None = None
    exclude: frozenset[str] = field(default_factory=frozenset)

    def as_dict(self) -> dict[str, Any]:
        return {
            "required_capabilities": sorted(self.required_capabilities),
            "estimated_tokens": self.estimated_tokens,
            "max_latency_s": self.max_latency_s,
            "exclude": sorted(self.exclude),
        }


@dataclass
class DispatchResult:
    ordered_candidates: list[ModelSpec] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    @property
    def best(self) -> ModelSpec | None:
        return self.ordered_candidates[0] if self.ordered_candidates else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.name if self.best else None,
            "ordered": [m.name for m in self.ordered_candidates],
            "rejected": self.rejected,
        }


# ── Dispatcher ──────────────────────────────────────────────

class LLMDispatcher:
    def __init__(self) -> None:
        self._models: dict[str, ModelSpec] = {}
        self._lock = threading.Lock()
        self._install_defaults()

    # ── Registration ───────────────────────────────────────

    def register(
        self,
        name: str,
        capabilities: set[str] | list[str],
        cost_per_1k_tokens: float,
        typical_latency_s: float = 1.0,
        max_tokens: int = 4096,
        provider: str = "",
    ) -> ModelSpec:
        name = name.strip()
        if not name:
            raise ValueError("model name required")
        spec = ModelSpec(
            name=name,
            capabilities=frozenset(capabilities),
            cost_per_1k_tokens=float(cost_per_1k_tokens),
            typical_latency_s=float(typical_latency_s),
            max_tokens=int(max_tokens),
            provider=provider,
        )
        with self._lock:
            self._models[name] = spec
        return spec

    def deregister(self, name: str) -> bool:
        with self._lock:
            return self._models.pop(name, None) is not None

    def registered(self) -> list[ModelSpec]:
        with self._lock:
            return list(self._models.values())

    # ── Dispatch ───────────────────────────────────────────

    def dispatch(self, request: Request) -> DispatchResult:
        result = DispatchResult()
        with self._lock:
            candidates = list(self._models.values())
        for m in candidates:
            if m.name in request.exclude:
                result.rejected.append((m.name, "excluded"))
                continue
            if not request.required_capabilities.issubset(m.capabilities):
                result.rejected.append((m.name, "missing capability"))
                continue
            if m.max_tokens < request.estimated_tokens:
                result.rejected.append((m.name, "context too small"))
                continue
            if (request.max_latency_s is not None
                    and m.typical_latency_s > request.max_latency_s):
                result.rejected.append((m.name, "latency cap"))
                continue
            if not self._provider_available(m):
                result.rejected.append((m.name, "provider unavailable"))
                continue
            result.ordered_candidates.append(m)
        # Cheapest first; ties broken by latency.
        result.ordered_candidates.sort(
            key=lambda m: (m.cost_per_1k_tokens, m.typical_latency_s),
        )
        return result

    def invoke(
        self,
        request: Request,
        call_fn: Callable[[ModelSpec], Any],
    ) -> tuple[ModelSpec | None, Any, list[tuple[str, str]]]:
        """Run ``call_fn(model)`` on the cheapest capable model,
        falling back down the ordered list on failure. Returns
        (model_used, result, errors_encountered)."""
        dispatch = self.dispatch(request)
        errors: list[tuple[str, str]] = []
        for model in dispatch.ordered_candidates:
            try:
                return model, call_fn(model), errors
            except Exception as exc:
                errors.append(
                    (model.name, f"{type(exc).__name__}: {exc}"),
                )
                self._record_failure(model)
                logger.debug(
                    "model %s failed: %s — falling back",
                    model.name, exc,
                )
        return None, None, errors

    # ── Provider helpers ───────────────────────────────────

    def _provider_available(self, model: ModelSpec) -> bool:
        """Ask rate_limiter + retry_policy whether we can call this
        provider right now. Both modules are optional; missing
        imports are treated as 'available'."""
        if not model.provider:
            return True
        try:
            from core.system.rate_limiter import registry as rl_reg
            spec = rl_reg().get(model.provider)
            if not spec.can_call():
                return False
        except Exception as exc:
            logger.debug("rate check unavailable: %s", exc)
        try:
            from core.system.retry_policy import registry as rt_reg
            if rt_reg().get(model.provider).is_open():
                return False
        except Exception as exc:
            logger.debug("retry check unavailable: %s", exc)
        return True

    def _record_failure(self, model: ModelSpec) -> None:
        if not model.provider:
            return
        try:
            from core.system.retry_policy import registry as rt_reg
            rt_reg().get(model.provider)._record_failure()
        except Exception as exc:
            logger.debug("retry failure record: %s", exc)

    # ── Defaults ──────────────────────────────────────────

    def _install_defaults(self) -> None:
        self.register(
            "groq_llama3_70b",
            capabilities={"classify", "summarise", "json"},
            cost_per_1k_tokens=0.0005,
            typical_latency_s=1.0,
            max_tokens=8192,
            provider="groq",
        )
        self.register(
            "gemini_flash",
            capabilities={"classify", "summarise", "multimodal",
                           "json", "long_context"},
            cost_per_1k_tokens=0.0008,
            typical_latency_s=2.5,
            max_tokens=1_000_000,
            provider="gemini",
        )
        self.register(
            "deepseek_v3",
            capabilities={"reason", "code", "json", "classify",
                           "summarise"},
            cost_per_1k_tokens=0.002,
            typical_latency_s=8.0,
            max_tokens=64000,
            provider="deepseek",
        )


# ── Singleton ────────────────────────────────────────────────

_DISP_LOCK = threading.Lock()
_DISPATCHER: LLMDispatcher | None = None


def dispatcher() -> LLMDispatcher:
    global _DISPATCHER
    if _DISPATCHER is None:
        with _DISP_LOCK:
            if _DISPATCHER is None:
                _DISPATCHER = LLMDispatcher()
    return _DISPATCHER
