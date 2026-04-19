"""Meta router — pick the best subsystem for a task.

ShopAI has ~60 brain subsystems. An incoming task ("should I kill
this ad?") could in principle be handled by half of them: decision
brain, policy_library, case_based_reasoner, critic_panel,
deliberation_loop, skill_library, etc. Hand-wiring which one handles
what doesn't scale.

meta_router lets each subsystem declare:

  • the capabilities it covers (e.g. "decision.kill_ad",
    "explanation.ads", "retrieval.cases")
  • an estimated cost (relative — lower is better)
  • an estimated latency (ms)
  • optionally, a competence lookup (callable returning 0..1)
    to query in real time

At call time, ``route(capability, budget=..., deadline=...)`` picks
the best subsystem:

    score = competence × (1/max(0.1,cost)) × deadline_fit
    deadline_fit = 1 if latency ≤ deadline else 0

Top-k selection so callers can ensemble or fall back.

Pure stdlib. Stateless beyond registration. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.meta_router")


@dataclass
class Provider:
    name: str
    capabilities: tuple[str, ...]
    cost: float = 1.0
    latency_ms: float = 50.0
    competence_fn: Callable[[str], float] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Provider.name required")
        if not self.capabilities:
            raise ValueError("Provider.capabilities required")
        if self.cost < 0:
            raise ValueError("cost must be non-negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")

    def competence_for(self, capability: str) -> float:
        if self.competence_fn is None:
            return 0.5
        try:
            return max(0.0, min(1.0, float(self.competence_fn(capability))))
        except Exception as exc:
            logger.debug(
                "competence_fn %s raised on %s: %s",
                self.name, capability, exc,
            )
            return 0.5

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": list(self.capabilities),
            "cost": round(self.cost, 4),
            "latency_ms": round(self.latency_ms, 2),
            "description": self.description,
        }


@dataclass
class RouteDecision:
    provider: str
    capability: str
    score: float
    competence: float
    cost: float
    latency_ms: float
    deadline_fit: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "capability": self.capability,
            "score": round(self.score, 4),
            "competence": round(self.competence, 4),
            "cost": round(self.cost, 4),
            "latency_ms": round(self.latency_ms, 2),
            "deadline_fit": self.deadline_fit,
        }


class MetaRouter:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    # ── Registration ─────────────────────────────────────

    def register(
        self, provider: Provider, overwrite: bool = False,
    ) -> None:
        if provider.name in self._providers and not overwrite:
            raise ValueError(
                f"provider {provider.name!r} already registered",
            )
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> bool:
        return self._providers.pop(name, None) is not None

    def providers(self) -> list[Provider]:
        return list(self._providers.values())

    def supporters_of(self, capability: str) -> list[Provider]:
        return [
            p for p in self._providers.values()
            if capability in p.capabilities
        ]

    # ── Routing ──────────────────────────────────────────

    def _score(
        self,
        provider: Provider, capability: str,
        *,
        budget: float | None,
        deadline_ms: float | None,
    ) -> tuple[float, RouteDecision]:
        competence = provider.competence_for(capability)
        deadline_fit = (
            deadline_ms is None
            or provider.latency_ms <= deadline_ms
        )
        if budget is not None and provider.cost > budget:
            return 0.0, RouteDecision(
                provider=provider.name,
                capability=capability,
                score=0.0, competence=competence,
                cost=provider.cost,
                latency_ms=provider.latency_ms,
                deadline_fit=deadline_fit,
            )
        if not deadline_fit:
            return 0.0, RouteDecision(
                provider=provider.name,
                capability=capability,
                score=0.0, competence=competence,
                cost=provider.cost,
                latency_ms=provider.latency_ms,
                deadline_fit=False,
            )
        score = competence / max(0.1, provider.cost)
        return score, RouteDecision(
            provider=provider.name,
            capability=capability,
            score=score, competence=competence,
            cost=provider.cost,
            latency_ms=provider.latency_ms,
            deadline_fit=True,
        )

    def route(
        self,
        capability: str,
        *,
        budget: float | None = None,
        deadline_ms: float | None = None,
        top_k: int = 1,
    ) -> list[RouteDecision]:
        if not capability:
            raise ValueError("capability required")
        if top_k < 1:
            raise ValueError("top_k must be ≥ 1")
        supporters = self.supporters_of(capability)
        scored: list[tuple[float, RouteDecision]] = []
        for p in supporters:
            s, decision = self._score(
                p, capability,
                budget=budget, deadline_ms=deadline_ms,
            )
            scored.append((s, decision))
        # Keep only non-zero scorers when any positive score exists;
        # otherwise surface the best-effort ineligible list so the
        # caller can see *why* nothing routed cleanly.
        has_positive = any(s > 0 for s, _ in scored)
        if has_positive:
            scored = [(s, d) for s, d in scored if s > 0]
        scored.sort(key=lambda kv: -kv[0])
        return [d for _, d in scored[:top_k]]

    def best(
        self,
        capability: str,
        **kwargs: Any,
    ) -> RouteDecision | None:
        results = self.route(capability, top_k=1, **kwargs)
        return results[0] if results else None

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        caps: set[str] = set()
        for p in self._providers.values():
            caps.update(p.capabilities)
        return {
            "providers": len(self._providers),
            "capabilities": sorted(caps),
            "capability_count": len(caps),
        }
