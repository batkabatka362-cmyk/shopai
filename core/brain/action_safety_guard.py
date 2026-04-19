"""Action safety guard — holistic pre-flight for money-moving actions.

The existing ``safety_envelope`` constrains the planner's search space
(numeric ranges, allowed values). The *action safety guard* sits later
in the pipeline: for every individual action about to fire on a live
Shopify / Meta / AutoDS adapter, it asks

    Is this action safe to execute RIGHT NOW, given:
      • the owner's bright lines
      • the blast radius of touching this many records
      • whether we even know how to roll it back

Three layers combine into one SafetyVerdict:

  1. **Bright-line rules** — absolute no-go patterns (never delete
     orders, never change store currency, never exceed $X/day ads).
  2. **Blast-radius** — single / batch / bulk / global scope classes,
     with owner-configurable policies per class.
  3. **Rollback feasibility** — is there a documented rollback, and
     has it been tested recently?

The verdict is the strictest level across layers: allow, require_approval,
or block. Block means "do not even queue it".

Complements feasibility_gate (hard/soft constraint filter) and
safety_envelope (planner search-space bound).

Pure stdlib. Deterministic. No LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


Verdict = Literal["allow", "require_approval", "block"]


@dataclass
class BrightLine:
    name: str
    predicate: Callable[[dict[str, Any]], bool]
    message: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("BrightLine.name required")

    def fires(self, action: dict[str, Any]) -> bool:
        try:
            return bool(self.predicate(action))
        except Exception:
            # Fail closed — unknown state treated as suspicious.
            return True


@dataclass
class BlastRadius:
    records_touched: int
    scope: Literal["single", "batch", "bulk", "global"]
    reversible: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "records_touched": self.records_touched,
            "scope": self.scope,
            "reversible": self.reversible,
        }


@dataclass
class SafetyVerdict:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    blast: BlastRadius | None = None
    rollback_known: bool = False
    rollback_last_tested_days: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "blast": self.blast.as_dict() if self.blast else None,
            "rollback_known": self.rollback_known,
            "rollback_last_tested_days":
                self.rollback_last_tested_days,
        }


def _classify_scope(n: int) -> Literal["single", "batch", "bulk", "global"]:
    if n <= 1:
        return "single"
    if n <= 25:
        return "batch"
    if n <= 500:
        return "bulk"
    return "global"


_VERDICT_RANK: dict[str, int] = {
    "allow": 0, "require_approval": 1, "block": 2,
}


def _escalate(current: Verdict, other: Verdict) -> Verdict:
    return other if _VERDICT_RANK[other] > _VERDICT_RANK[current] else current


class ActionSafetyGuard:
    def __init__(
        self,
        *,
        batch_requires_approval: bool = False,
        bulk_requires_approval: bool = True,
        global_blocks: bool = True,
        unreversible_min_confidence: float = 0.85,
        rollback_stale_days: int = 30,
    ) -> None:
        self._bright_lines: list[BrightLine] = []
        self._rollback_recipes: dict[str, dict[str, Any]] = {}
        self._batch_requires_approval = batch_requires_approval
        self._bulk_requires_approval = bulk_requires_approval
        self._global_blocks = global_blocks
        self._unreversible_min_confidence = float(
            unreversible_min_confidence,
        )
        self._rollback_stale_days = int(rollback_stale_days)

    # ── Bright lines ──────────────────────────────────────

    def add_bright_line(self, rule: BrightLine) -> None:
        self._bright_lines.append(rule)

    def clear_bright_lines(self) -> None:
        self._bright_lines.clear()

    def bright_lines(self) -> list[BrightLine]:
        return list(self._bright_lines)

    # ── Rollback recipes ──────────────────────────────────

    def register_rollback(
        self,
        action_kind: str,
        *,
        steps: list[str],
        last_tested_days: int | None = None,
    ) -> None:
        if not action_kind:
            raise ValueError("action_kind required")
        if not steps:
            raise ValueError("rollback needs at least one step")
        self._rollback_recipes[action_kind] = {
            "steps": list(steps),
            "last_tested_days": last_tested_days,
        }

    def rollback_known(self, action_kind: str) -> bool:
        return action_kind in self._rollback_recipes

    # ── Evaluate ─────────────────────────────────────────

    def evaluate(
        self,
        action: dict[str, Any],
        *,
        blast: BlastRadius | None = None,
        confidence: float = 1.0,
    ) -> SafetyVerdict:
        reasons: list[str] = []
        verdict: Verdict = "allow"

        # Bright lines first — any fire ⇒ hard block
        for rule in self._bright_lines:
            if rule.fires(action):
                reasons.append(
                    f"bright_line:{rule.name}"
                    + (f": {rule.message}" if rule.message else "")
                )
                verdict = "block"

        # Blast radius
        if blast is None:
            n = int(action.get("records_touched", 1) or 1)
            reversible = bool(action.get("reversible", True))
            blast = BlastRadius(
                records_touched=n, scope=_classify_scope(n),
                reversible=reversible,
            )
        if verdict != "block":
            if blast.scope == "global" and self._global_blocks:
                reasons.append(
                    f"blast:global ({blast.records_touched} "
                    "records) — explicit override required",
                )
                verdict = "block"
            elif blast.scope == "bulk" and self._bulk_requires_approval:
                reasons.append(
                    f"blast:bulk ({blast.records_touched} records) "
                    "requires approval",
                )
                verdict = _escalate(verdict, "require_approval")
            elif blast.scope == "batch" and self._batch_requires_approval:
                reasons.append(
                    f"blast:batch ({blast.records_touched} records) "
                    "requires approval",
                )
                verdict = _escalate(verdict, "require_approval")

        # Rollback
        kind = str(action.get("kind", "")) or str(action.get("action", ""))
        rollback_known = self.rollback_known(kind)
        last_tested: int | None = None
        if rollback_known:
            last_tested = self._rollback_recipes[kind].get(
                "last_tested_days",
            )
        if verdict != "block":
            if not blast.reversible or not rollback_known:
                if confidence < self._unreversible_min_confidence:
                    reasons.append(
                        "rollback_missing_or_irreversible with "
                        f"confidence {confidence:.2f} < "
                        f"{self._unreversible_min_confidence:.2f}",
                    )
                    verdict = _escalate(verdict, "require_approval")
            if (
                last_tested is not None
                and last_tested > self._rollback_stale_days
            ):
                reasons.append(
                    f"rollback_recipe stale ({last_tested}d > "
                    f"{self._rollback_stale_days}d)",
                )
                verdict = _escalate(verdict, "require_approval")

        return SafetyVerdict(
            verdict=verdict, reasons=reasons,
            blast=blast,
            rollback_known=rollback_known,
            rollback_last_tested_days=last_tested,
        )

    def stats(self) -> dict[str, Any]:
        return {
            "bright_lines": len(self._bright_lines),
            "rollback_recipes": len(self._rollback_recipes),
        }


# ── Canonical bright-line builders ────────────────────────

def never_delete_orders() -> BrightLine:
    return BrightLine(
        name="never_delete_orders",
        predicate=lambda a: (
            a.get("kind") == "delete"
            and "order" in str(a.get("target", ""))
        ),
        message="order deletion is never allowed",
    )


def never_change_currency() -> BrightLine:
    return BrightLine(
        name="never_change_currency",
        predicate=lambda a: (
            "currency" in str(a.get("field", "")).lower()
            and a.get("kind") in ("set", "update", "change")
        ),
        message="store currency must not be changed autonomously",
    )


def daily_ads_cap(max_usd: float) -> BrightLine:
    return BrightLine(
        name=f"daily_ads_cap_{int(max_usd)}",
        predicate=lambda a: (
            str(a.get("target_kind", "")) == "ads"
            and float(a.get("budget_change_usd", 0) or 0) > max_usd
        ),
        message=f"single-action ads spend must stay ≤ ${max_usd}",
    )
