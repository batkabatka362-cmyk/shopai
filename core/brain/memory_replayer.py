"""Memory replayer — sleep-style episode replay over experience.

The hippocampal-replay analogy: during downtime, we replay past
episodes (decisions + outcomes) and re-evaluate them under the
*current* policy. That surfaces missed wins ("we shouldn't have
killed that ad") and missed losses ("this rule keeps firing on
losers").

Pure stdlib, deterministic. Works directly on the experience_recorder
ledger but accepts an injected ``recent`` callable for tests.

Two main modes:

  • ``replay_outcomes(policy, kind="outcome", limit=200)``
    Walk recent outcomes, apply the policy to the recorded
    (context, kpi) pair, and report agreement / divergence /
    over-time drift.

  • ``find_missed_patterns(min_support=5)``
    Cluster recent (decision, outcome_sign) pairs by context and
    flag clusters where the brain *consistently* picked the wrong
    action. These are candidates for the rule promotion engine.

Output is structured (ReplayReport / MissedPattern dataclasses) so
callers — daemon housekeep + cycle_planner — can act on it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.memory_replayer")


PolicyFn = Callable[[dict[str, Any]], str | None]


@dataclass
class ReplayReport:
    inspected: int
    agreed: int
    diverged: int
    examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def agreement_rate(self) -> float:
        if self.inspected == 0:
            return 0.0
        return self.agreed / self.inspected

    def as_dict(self) -> dict[str, Any]:
        return {
            "inspected": self.inspected,
            "agreed": self.agreed,
            "diverged": self.diverged,
            "agreement_rate": round(self.agreement_rate, 4),
            "examples": list(self.examples),
        }


@dataclass
class MissedPattern:
    signature: str
    n_total: int
    n_wrong: int
    sample_decision: str
    sample_outcome_value: float

    @property
    def wrong_rate(self) -> float:
        if self.n_total == 0:
            return 0.0
        return self.n_wrong / self.n_total

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "n_total": self.n_total,
            "n_wrong": self.n_wrong,
            "wrong_rate": round(self.wrong_rate, 4),
            "sample_decision": self.sample_decision,
            "sample_outcome_value": round(self.sample_outcome_value, 4),
        }


# ── Helpers ───────────────────────────────────────────────

def _payload(event: Any) -> dict[str, Any]:
    p = getattr(event, "payload", None)
    if p is None and isinstance(event, dict):
        p = event.get("payload")
    return p if isinstance(p, dict) else {}


def _kind(event: Any) -> str:
    return str(
        getattr(event, "kind", None)
        or (event.get("kind") if isinstance(event, dict) else "")
    )


def _signature(context: dict[str, Any], drop: tuple[str, ...] = ()) -> str:
    """Stable hashable signature of a context — sorted key=value pairs
    with a small ``drop`` list for high-cardinality keys we want to
    ignore (e.g. timestamps, ids)."""
    parts: list[str] = []
    for k in sorted(context):
        if k in drop:
            continue
        parts.append(f"{k}={context[k]}")
    return "|".join(parts)


# ── Replayer ──────────────────────────────────────────────

class MemoryReplayer:
    def __init__(
        self,
        recent_fn: Callable[..., list[Any]] | None = None,
    ) -> None:
        self._recent_fn = recent_fn

    def _recent(self, **kwargs: Any) -> list[Any]:
        if self._recent_fn is not None:
            try:
                return list(self._recent_fn(**kwargs))
            except Exception as exc:
                logger.debug("recent_fn failed: %s", exc)
                return []
        try:
            from core.brain.experience_recorder import recent
            return list(recent(**kwargs))
        except Exception as exc:
            logger.debug("default recent failed: %s", exc)
            return []

    # ── Mode 1: replay outcomes against a policy ──────────

    def replay_outcomes(
        self,
        policy: PolicyFn,
        *,
        limit: int = 200,
    ) -> ReplayReport:
        """Walk recent decisions; for each, ask the policy what it
        WOULD do today and compare with what it did then."""
        events = self._recent(kind="decision", limit=limit)
        agreed = 0
        diverged = 0
        examples: list[dict[str, Any]] = []
        for ev in events:
            payload = _payload(ev)
            context = payload.get("context") or {}
            chosen = (payload.get("chosen") or {}) or {}
            past_action = (
                chosen.get("action") or chosen.get("kind") or ""
            )
            try:
                now_action = policy(context)
            except Exception as exc:
                logger.debug("policy raised: %s", exc)
                continue
            if now_action is None:
                continue
            if now_action == past_action:
                agreed += 1
            else:
                diverged += 1
                if len(examples) < 5:
                    examples.append({
                        "context": context,
                        "past": past_action,
                        "now": now_action,
                    })
        return ReplayReport(
            inspected=agreed + diverged,
            agreed=agreed,
            diverged=diverged,
            examples=examples,
        )

    # ── Mode 2: find missed patterns ──────────────────────

    def find_missed_patterns(
        self,
        *,
        limit: int = 500,
        min_support: int = 5,
        wrong_threshold: float = 0.6,
        drop_keys: tuple[str, ...] = ("ts", "cycle_id"),
    ) -> list[MissedPattern]:
        """Cluster (decision_signature, outcome_was_negative) and
        return clusters where the brain repeatedly picks losers.

        outcome_value < 0 OR success == False is treated as wrong.
        """
        decisions = self._recent(kind="decision", limit=limit)
        outcomes = self._recent(kind="outcome", limit=limit)

        # Index outcomes by cycle_id so we can pair them with decisions.
        outcomes_by_cycle: dict[str, list[Any]] = defaultdict(list)
        for o in outcomes:
            cid = (
                getattr(o, "cycle_id", None)
                or (o.get("cycle_id") if isinstance(o, dict) else "")
                or ""
            )
            outcomes_by_cycle[str(cid)].append(o)

        clusters: dict[str, list[tuple[str, float]]] = defaultdict(list)
        decision_samples: dict[str, str] = {}
        for d in decisions:
            payload = _payload(d)
            context = payload.get("context") or {}
            chosen = payload.get("chosen") or {}
            decision_str = str(
                chosen.get("action") or chosen.get("kind") or "?"
            )
            sig = _signature(context, drop=drop_keys)
            if not sig:
                continue
            cid = (
                getattr(d, "cycle_id", None)
                or (d.get("cycle_id") if isinstance(d, dict) else "")
                or ""
            )
            paired = outcomes_by_cycle.get(str(cid), [])
            for o in paired:
                op = _payload(o)
                value = float(op.get("value", 0.0) or 0.0)
                clusters[sig].append((decision_str, value))
                decision_samples.setdefault(sig, decision_str)

        out: list[MissedPattern] = []
        for sig, members in clusters.items():
            if len(members) < min_support:
                continue
            wrong = sum(1 for _, v in members if v <= 0)
            if wrong / len(members) >= wrong_threshold:
                sample_decision = decision_samples.get(sig, "?")
                sample_value = members[-1][1] if members else 0.0
                out.append(MissedPattern(
                    signature=sig,
                    n_total=len(members),
                    n_wrong=wrong,
                    sample_decision=sample_decision,
                    sample_outcome_value=sample_value,
                ))
        out.sort(key=lambda p: -p.wrong_rate)
        return out

    # ── Mode 3: stratified sample for retraining ──────────

    def sample(
        self,
        *,
        kind: str = "decision",
        limit: int = 100,
    ) -> list[Any]:
        """Recent events of a given kind, ordered newest-first.
        Returned as opaque experience records the caller already
        knows how to interpret."""
        return self._recent(kind=kind, limit=limit)

    def stats(self) -> dict[str, Any]:
        decisions = self._recent(kind="decision", limit=1)
        outcomes = self._recent(kind="outcome", limit=1)
        return {
            "decisions_visible": bool(decisions),
            "outcomes_visible": bool(outcomes),
        }
