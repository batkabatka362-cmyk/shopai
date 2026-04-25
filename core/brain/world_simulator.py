"""World simulator — dry-run state transitions before writing live.

SmartExecutor has a simulate → dry_run → live pipeline but each
adapter does its own. The world simulator is a *unified* in-memory
model of the world state (products, orders, inventory, ad budgets)
with registered state-transition functions per action kind. Callers
can:

  1. Seed the simulator from a real snapshot.
  2. Apply a sequence of candidate actions.
  3. Read the resulting state + a diff.
  4. Reset and try a different sequence.

Every transition is a pure function ``(state, action) -> new_state``
registered under an action kind. Unknown kinds return the state
unchanged with a warning captured in the diff.

Use cases:
  • plan_verifier already walks preconditions; this adds realistic
    effects.
  • counterfactual_simulator rolls out with a transition model — the
    world simulator IS that model, reusable across rollouts.
  • UI "what would happen if…" sliders.

Pure stdlib. Deterministic. Thread-safe (Lock).
"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.world_simulator")


StateDict = dict[str, Any]
TransitionFn = Callable[[StateDict, dict[str, Any]], StateDict]


@dataclass
class TransitionResult:
    action_kind: str
    changed_keys: list[str] = field(default_factory=list)
    added_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_kind": self.action_kind,
            "changed_keys": list(self.changed_keys),
            "added_keys": list(self.added_keys),
            "removed_keys": list(self.removed_keys),
            "note": self.note,
        }


@dataclass
class SimulationReport:
    final_state: StateDict
    applied: list[TransitionResult] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_state_keys": sorted(self.final_state.keys()),
            "applied": [a.as_dict() for a in self.applied],
            "skipped": list(self.skipped),
        }


# ── Diff helpers ─────────────────────────────────────────

def _diff(before: StateDict, after: StateDict) -> TransitionResult:
    before_keys = set(before.keys())
    after_keys = set(after.keys())
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    changed: list[str] = []
    for k in before_keys & after_keys:
        if before[k] != after[k]:
            changed.append(k)
    return TransitionResult(
        action_kind="",
        changed_keys=changed,
        added_keys=added,
        removed_keys=removed,
    )


class WorldSimulator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: StateDict = {}
        self._transitions: dict[str, TransitionFn] = {}

    # ── Registration ─────────────────────────────────────

    def register(
        self, action_kind: str, fn: TransitionFn,
        *, overwrite: bool = False,
    ) -> None:
        if not action_kind:
            raise ValueError("action_kind required")
        with self._lock:
            if action_kind in self._transitions and not overwrite:
                raise ValueError(
                    f"transition {action_kind!r} already registered",
                )
            self._transitions[action_kind] = fn

    def unregister(self, action_kind: str) -> bool:
        with self._lock:
            return self._transitions.pop(action_kind, None) is not None

    def kinds(self) -> list[str]:
        with self._lock:
            return sorted(self._transitions.keys())

    # ── State ───────────────────────────────────────────

    def seed(self, state: StateDict) -> None:
        with self._lock:
            self._state = copy.deepcopy(dict(state or {}))

    def state(self) -> StateDict:
        with self._lock:
            return copy.deepcopy(self._state)

    def reset(self) -> None:
        with self._lock:
            self._state = {}

    # ── Apply ────────────────────────────────────────────

    def _apply_one(
        self, action: dict[str, Any],
    ) -> tuple[bool, TransitionResult | dict[str, Any]]:
        kind = str(action.get("kind", ""))
        if not kind:
            return False, {
                "action": action,
                "reason": "missing kind",
            }
        fn = self._transitions.get(kind)
        if fn is None:
            return False, {
                "action": action,
                "reason": f"no transition registered for {kind!r}",
            }
        before = copy.deepcopy(self._state)
        try:
            after = fn(before, dict(action))
        except Exception as exc:
            logger.debug(
                "transition %s raised: %s", kind, exc,
            )
            return False, {
                "action": action,
                "reason": f"transition raised: {exc}",
            }
        if not isinstance(after, dict):
            return False, {
                "action": action,
                "reason": "transition did not return a state dict",
            }
        diff = _diff(self._state, after)
        diff.action_kind = kind
        self._state = after
        return True, diff

    def apply(
        self, actions: Iterable[dict[str, Any]],
    ) -> SimulationReport:
        applied: list[TransitionResult] = []
        skipped: list[dict[str, Any]] = []
        with self._lock:
            for action in actions:
                ok, result = self._apply_one(action)
                if ok:
                    applied.append(result)  # type: ignore[arg-type]
                else:
                    skipped.append(result)  # type: ignore[arg-type]
            final = copy.deepcopy(self._state)
        return SimulationReport(
            final_state=final,
            applied=applied,
            skipped=skipped,
        )

    def preview(
        self, actions: Iterable[dict[str, Any]],
    ) -> SimulationReport:
        """Run an action sequence without mutating the stored state."""
        with self._lock:
            snapshot = copy.deepcopy(self._state)
        try:
            report = self.apply(actions)
        finally:
            with self._lock:
                self._state = snapshot
        return report

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "registered_kinds": len(self._transitions),
                "state_keys": sorted(self._state.keys()),
            }


# ── Canonical transitions (owner-optional) ────────────────

def _set_price(state: StateDict, action: dict[str, Any]) -> StateDict:
    sku = str(action.get("sku", ""))
    price = float(action.get("price", 0.0))
    if not sku:
        return state
    out = copy.deepcopy(state)
    products = dict(out.get("products", {}))
    prod = dict(products.get(sku, {}))
    prod["price"] = price
    products[sku] = prod
    out["products"] = products
    return out


def _adjust_inventory(
    state: StateDict, action: dict[str, Any],
) -> StateDict:
    sku = str(action.get("sku", ""))
    delta = int(action.get("delta", 0))
    if not sku:
        return state
    out = copy.deepcopy(state)
    products = dict(out.get("products", {}))
    prod = dict(products.get(sku, {}))
    prod["on_hand"] = int(prod.get("on_hand", 0)) + delta
    products[sku] = prod
    out["products"] = products
    return out


def _set_ad_budget(
    state: StateDict, action: dict[str, Any],
) -> StateDict:
    ad = str(action.get("ad_id", ""))
    daily = float(action.get("daily_usd", 0.0))
    if not ad:
        return state
    out = copy.deepcopy(state)
    ads = dict(out.get("ads", {}))
    row = dict(ads.get(ad, {}))
    row["daily_usd"] = daily
    ads[ad] = row
    out["ads"] = ads
    return out


def default_transitions() -> dict[str, TransitionFn]:
    """Owner-optional canonical transitions for the common actions."""
    return {
        "set_price": _set_price,
        "adjust_inventory": _adjust_inventory,
        "set_ad_budget": _set_ad_budget,
    }
