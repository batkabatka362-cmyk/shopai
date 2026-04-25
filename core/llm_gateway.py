"""LLM gateway — the single front door for every Claude/Groq/Gemini call.

Owner instruction: *"AI models or cloud AI should ALWAYS go through
core"*. This module enforces that rule. No engine, adapter, or phase
should hit an LLM directly. They must call ``ask()`` here. We then:

  1. Route through ``core.adapters.router.get_router()`` (fallback chain
     Groq → Gemini → DeepSeek → …).
  2. Attach a ``RouteContext`` with cost + latency caps derived from
     the *purpose* tag (see CLAUDE.md §4b.C budget table).
  3. Record every call to the experience recorder so the brain can
     learn from its own LLM behaviour (cost, latency, success rate).
  4. Optionally mirror the prompt+completion into the Obsidian vault
     when the call is tagged ``learnable=True``.

Public API:

    ask(
        prompt: str,
        system: str | None = None,
        purpose: str = "reasoning",   # bulk | content | reasoning | cycle_block
        max_cost: float | None = None,
        max_latency_ms: int | None = None,
        learnable: bool = False,
        context: dict | None = None,
    ) -> GatewayResult

Pure stdlib (orchestration only — real work goes through adapters).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from utils.logger import get_logger


logger = get_logger("llm_gateway")


# Cost / latency budgets by purpose — aligned with CLAUDE.md §4b.C.
_BUDGETS: dict[str, dict[str, float]] = {
    "bulk":         {"max_cost": 0.0005, "max_latency_ms": 2_000},
    "content":      {"max_cost": 0.005,  "max_latency_ms": 8_000},
    "reasoning":    {"max_cost": 0.05,   "max_latency_ms": 30_000},
    # cycle_block means NO LLM at all; caller must be deterministic.
    "cycle_block":  {"max_cost": 0.0,    "max_latency_ms": 0},
}


Purpose = Literal["bulk", "content", "reasoning", "cycle_block"]


@dataclass
class GatewayResult:
    ok: bool
    text: str = ""
    adapter: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str = ""
    purpose: str = "reasoning"

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "adapter": self.adapter,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": round(self.latency_ms, 1),
            "purpose": self.purpose,
            "error": self.error,
        }


# ── Singleton call counter so the facade can report LLM use ────

_LOCK = threading.Lock()
_CALL_STATS: dict[str, Any] = {
    "total_calls": 0,
    "total_cost_usd": 0.0,
    "total_latency_ms": 0.0,
    "by_purpose": {},
    "by_adapter": {},
    "failures": 0,
}


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "total_calls": _CALL_STATS["total_calls"],
            "total_cost_usd": round(_CALL_STATS["total_cost_usd"], 4),
            "total_latency_ms": round(_CALL_STATS["total_latency_ms"], 1),
            "avg_latency_ms": round(
                _CALL_STATS["total_latency_ms"]
                / max(1, _CALL_STATS["total_calls"]),
                1,
            ),
            "by_purpose": dict(_CALL_STATS["by_purpose"]),
            "by_adapter": dict(_CALL_STATS["by_adapter"]),
            "failures": _CALL_STATS["failures"],
        }


def _record_stats(result: GatewayResult) -> None:
    with _LOCK:
        _CALL_STATS["total_calls"] += 1
        _CALL_STATS["total_cost_usd"] += float(result.cost_usd or 0.0)
        _CALL_STATS["total_latency_ms"] += float(result.latency_ms or 0.0)
        bp = _CALL_STATS["by_purpose"]
        bp[result.purpose] = bp.get(result.purpose, 0) + 1
        if result.adapter:
            ba = _CALL_STATS["by_adapter"]
            ba[result.adapter] = ba.get(result.adapter, 0) + 1
        if not result.ok:
            _CALL_STATS["failures"] += 1


# ── Cost estimator — uses published token rates ───────────────

# Per 1M tokens (input/output), rough rates as of 2026. Used when
# the adapter itself doesn't report cost.
_RATE_TABLE: dict[str, tuple[float, float]] = {
    "groq":      (0.05, 0.08),
    "gemini":    (0.15, 0.60),
    "deepseek":  (0.14, 0.28),
    "openrouter":(0.50, 1.50),
    "huggingface": (0.0, 0.0),
    "ollama":    (0.0, 0.0),
}


def _estimate_cost(
    adapter: str, tokens_in: int, tokens_out: int,
) -> float:
    rates = _RATE_TABLE.get(adapter.lower(), (0.0, 0.0))
    return (tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000


# ── Main entry point ──────────────────────────────────────────

def ask(
    prompt: str,
    *,
    system: str | None = None,
    purpose: Purpose = "reasoning",
    max_cost: float | None = None,
    max_latency_ms: int | None = None,
    learnable: bool = False,
    context: dict[str, Any] | None = None,
) -> GatewayResult:
    """Single entry point for every LLM call in ShopAI."""
    if not prompt or not isinstance(prompt, str):
        return GatewayResult(
            ok=False, error="empty or invalid prompt",
            purpose=purpose,
        )
    if purpose == "cycle_block":
        return GatewayResult(
            ok=False,
            error="cycle_block: caller must be deterministic",
            purpose=purpose,
        )

    budget = _BUDGETS.get(purpose, _BUDGETS["reasoning"])
    cap_cost = float(max_cost if max_cost is not None else budget["max_cost"])
    cap_latency = int(
        max_latency_ms if max_latency_ms is not None
        else budget["max_latency_ms"]
    )
    started = time.monotonic()

    try:
        from core.adapters import get_router, Capability, RouteContext
        router = get_router()
        route_ctx = RouteContext(
            budget_usd=cap_cost,
            max_latency_ms=cap_latency,
        )
        params: dict[str, Any] = {"prompt": prompt}
        if system:
            params["system"] = system
        if context:
            params["context"] = context
        adapter_result = router.execute(
            Capability.CHAT_COMPLETE, params, context=route_ctx,
        )
        latency_ms = (time.monotonic() - started) * 1000.0
        text = ""
        if adapter_result.ok:
            data = adapter_result.data or {}
            text = str(data.get("text", ""))
        tokens_in = int(getattr(adapter_result, "tokens_in", 0) or 0)
        tokens_out = int(getattr(adapter_result, "tokens_out", 0) or 0)
        adapter_name = str(getattr(adapter_result, "adapter", "") or "")
        cost = _estimate_cost(adapter_name, tokens_in, tokens_out)
        result = GatewayResult(
            ok=bool(adapter_result.ok),
            text=text,
            adapter=adapter_name,
            model=str(getattr(adapter_result, "model", "") or ""),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency_ms,
            error=(
                "" if adapter_result.ok
                else str(getattr(adapter_result, "error", "unknown"))
            ),
            purpose=purpose,
        )
    except ImportError as exc:
        logger.debug("gateway router unavailable: %s", exc)
        result = _legacy_fallback(
            prompt, system, purpose, started,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - started) * 1000.0
        logger.warning("gateway error: %s", exc)
        result = GatewayResult(
            ok=False, error=f"{type(exc).__name__}: {exc}",
            latency_ms=latency_ms, purpose=purpose,
        )

    _record_stats(result)
    _optional_record_experience(prompt, result, learnable)
    return result


def _legacy_fallback(
    prompt: str, system: str | None, purpose: str, started: float,
) -> GatewayResult:
    """Last-resort path when the adapter router is unavailable."""
    try:
        from core.system.llm_adapter import get_llm
        llm = get_llm()
        response = llm.ask(system or "assistant", prompt)
        latency_ms = (time.monotonic() - started) * 1000.0
        return GatewayResult(
            ok=bool(getattr(response, "success", False)),
            text=str(getattr(response, "text", "") or ""),
            adapter="legacy",
            model=str(getattr(response, "model", "") or ""),
            latency_ms=latency_ms,
            purpose=purpose,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - started) * 1000.0
        return GatewayResult(
            ok=False, error=f"legacy_llm_unavailable: {exc}",
            latency_ms=latency_ms, purpose=purpose,
        )


def _optional_record_experience(
    prompt: str, result: GatewayResult, learnable: bool,
) -> None:
    """Pipe the call to experience_recorder when it's loaded."""
    try:
        from core.brain.experience_recorder import record_llm_call
        record_llm_call(prompt=prompt, result=result, learnable=learnable)
    except ImportError:
        # experience_recorder not yet wired — skip silently
        return
    except Exception as exc:
        logger.debug("experience_recorder call failed: %s", exc)
