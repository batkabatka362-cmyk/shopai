"""Recovery planner — when an invariant breaks, suggest ranked recovery plans.

invariant_monitor detects breaches; plan_repair patches single workflow
steps. recovery_planner bridges the two: given a concrete breach
(inventory went negative, refund queue grew past SLA), it looks up
pre-registered ``RecoveryPlaybook`` entries keyed by the invariant
name and scores them by:

  • priority    — higher fires first (owner-set)
  • blast_radius — smaller is safer
  • confidence  — caller-provided estimate of success
  • cost_usd    — lower preferred (tie-breaker)

Ranked output lets a daemon pick the top playbook or ask the owner to
choose. Pure stdlib. Deterministic.

Typical use:

    planner.register(RecoveryPlaybook(
        invariant="inventory_non_negative",
        name="restock_from_backup_warehouse",
        steps=["pull SKUs from backup", "update inventory", "notify"],
        blast_radius=3,
        cost_usd=50.0,
        confidence=0.85,
        priority=10,
    ))
    ranked = planner.plan_for_breach("inventory_non_negative",
                                      context={"sku": "p1"})
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.recovery_planner")


@dataclass
class RecoveryPlaybook:
    invariant: str
    name: str
    steps: list[str] = field(default_factory=list)
    blast_radius: int = 1
    cost_usd: float = 0.0
    confidence: float = 0.5
    priority: int = 0
    tags: tuple[str, ...] = ()
    preconditions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.invariant:
            raise ValueError("invariant required")
        if not self.name:
            raise ValueError("name required")
        if not self.steps:
            raise ValueError("steps required")
        if self.blast_radius < 1:
            raise ValueError("blast_radius must be ≥ 1")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be ≥ 0")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be 0..1")

    def applies_to(self, context: dict[str, Any]) -> bool:
        """All preconditions literally match context keys."""
        for k, v in self.preconditions.items():
            if context.get(k) != v:
                return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "invariant": self.invariant,
            "name": self.name,
            "steps": list(self.steps),
            "blast_radius": self.blast_radius,
            "cost_usd": round(self.cost_usd, 4),
            "confidence": round(self.confidence, 4),
            "priority": self.priority,
            "tags": list(self.tags),
            "preconditions": dict(self.preconditions),
        }


@dataclass
class RecoveryRanked:
    playbook: RecoveryPlaybook
    score: float
    why: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "playbook": self.playbook.as_dict(),
            "score": round(self.score, 4),
            "why": list(self.why),
        }


class RecoveryPlanner:
    def __init__(
        self,
        *,
        blast_penalty: float = 0.05,
        priority_weight: float = 0.1,
    ) -> None:
        if blast_penalty < 0 or priority_weight < 0:
            raise ValueError("weights must be non-negative")
        self._blast_penalty = float(blast_penalty)
        self._priority_weight = float(priority_weight)
        self._playbooks: list[RecoveryPlaybook] = []

    # ── Registration ─────────────────────────────────────

    def register(self, playbook: RecoveryPlaybook) -> None:
        self._playbooks.append(playbook)

    def unregister(self, invariant: str, name: str) -> bool:
        before = len(self._playbooks)
        self._playbooks = [
            p for p in self._playbooks
            if not (p.invariant == invariant and p.name == name)
        ]
        return len(self._playbooks) < before

    def playbooks(
        self, invariant: str | None = None,
    ) -> list[RecoveryPlaybook]:
        if invariant is None:
            return list(self._playbooks)
        return [p for p in self._playbooks if p.invariant == invariant]

    # ── Scoring ──────────────────────────────────────────

    def _score(
        self,
        playbook: RecoveryPlaybook,
    ) -> tuple[float, list[str]]:
        why: list[str] = []
        why.append(f"confidence={playbook.confidence:.2f}")
        score = playbook.confidence
        # Penalise larger blast radii linearly
        blast_cost = self._blast_penalty * playbook.blast_radius
        why.append(f"-blast={blast_cost:.3f}")
        score -= blast_cost
        # Add priority bonus
        bonus = self._priority_weight * playbook.priority
        why.append(f"+priority={bonus:.3f}")
        score += bonus
        # Tiny cost deduction (normalise to $100 = 0.1 points)
        cost_ded = min(1.0, playbook.cost_usd / 1000.0)
        why.append(f"-cost={cost_ded:.4f}")
        score -= cost_ded
        return score, why

    # ── Plan ─────────────────────────────────────────────

    def plan_for_breach(
        self,
        invariant: str,
        *,
        context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[RecoveryRanked]:
        if not invariant:
            raise ValueError("invariant required")
        if top_k < 1:
            raise ValueError("top_k must be ≥ 1")
        ctx = dict(context or {})
        candidates = [
            p for p in self._playbooks
            if p.invariant == invariant and p.applies_to(ctx)
        ]
        ranked: list[RecoveryRanked] = []
        for p in candidates:
            score, why = self._score(p)
            ranked.append(RecoveryRanked(
                playbook=p, score=score, why=why,
            ))
        ranked.sort(key=lambda r: -r.score)
        return ranked[:top_k]

    def best_for_breach(
        self,
        invariant: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> RecoveryRanked | None:
        top = self.plan_for_breach(
            invariant, context=context, top_k=1,
        )
        return top[0] if top else None

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        by_inv: dict[str, int] = {}
        for p in self._playbooks:
            by_inv[p.invariant] = by_inv.get(p.invariant, 0) + 1
        return {
            "playbooks": len(self._playbooks),
            "invariants_covered": len(by_inv),
            "by_invariant": by_inv,
        }
