"""Temporal logic — LTL-lite rules over event traces.

temporal (v5) captures simple time-based patterns but doesn't
express structural claims like "after every kill, a launch
follows within 7 days" or "a refund never comes before an order".
Linear Temporal Logic handles that cleanly.

We implement three classic LTL operators plus an 'implies' helper,
evaluated over a finite trace (ordered list of Event).

  always(φ)     — φ holds in every state
  eventually(φ) — φ holds in some future state
  next(φ)       — φ holds in the next state
  never(φ)      — φ never holds in any state

Formulas are built with thin dataclass nodes so the parser and
evaluator are tiny. Predicates over events are plain callables.

APIs:

  evaluate(formula, trace) → TemporalResult(ok, witness?, violation?)
  check_rules(trace, rules) → list[TemporalResult]

Zero LLM. Deterministic. Pure stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal


Predicate = Callable[[dict[str, Any]], bool]


# ── Formula AST ────────────────────────────────────────────

@dataclass
class Always:
    pred: Predicate
    name: str = ""


@dataclass
class Eventually:
    pred: Predicate
    name: str = ""


@dataclass
class Next:
    pred: Predicate
    name: str = ""


@dataclass
class Never:
    pred: Predicate
    name: str = ""


@dataclass
class Implies:
    antecedent: Predicate
    consequent: Predicate
    within: int | None = None       # within N future steps
    name: str = ""


Formula = Always | Eventually | Next | Never | Implies


@dataclass
class TemporalResult:
    formula: str
    ok: bool
    witness_index: int | None = None     # for Eventually / Implies success
    violation_index: int | None = None    # for Always / Never failure
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula,
            "ok": self.ok,
            "witness_index": self.witness_index,
            "violation_index": self.violation_index,
            "detail": self.detail,
        }


# ── Evaluator ───────────────────────────────────────────────

def evaluate(
    formula: Formula,
    trace: Iterable[dict[str, Any]],
) -> TemporalResult:
    trace = list(trace)
    label = _label(formula)

    if isinstance(formula, Always):
        for i, ev in enumerate(trace):
            if not _safe_pred(formula.pred, ev):
                return TemporalResult(
                    formula=label, ok=False,
                    violation_index=i,
                    detail=f"broken at step {i}",
                )
        return TemporalResult(
            formula=label, ok=True,
            detail=f"held across {len(trace)} step(s)",
        )

    if isinstance(formula, Never):
        for i, ev in enumerate(trace):
            if _safe_pred(formula.pred, ev):
                return TemporalResult(
                    formula=label, ok=False,
                    violation_index=i,
                    detail=f"triggered at step {i}",
                )
        return TemporalResult(
            formula=label, ok=True,
            detail=f"never seen across {len(trace)} step(s)",
        )

    if isinstance(formula, Eventually):
        for i, ev in enumerate(trace):
            if _safe_pred(formula.pred, ev):
                return TemporalResult(
                    formula=label, ok=True,
                    witness_index=i,
                    detail=f"witnessed at step {i}",
                )
        return TemporalResult(
            formula=label, ok=False,
            detail=f"never witnessed across {len(trace)} step(s)",
        )

    if isinstance(formula, Next):
        if len(trace) < 1:
            return TemporalResult(
                formula=label, ok=False,
                detail="empty trace",
            )
        # Next(φ) at position 0 means φ holds at trace[1]
        if len(trace) < 2:
            return TemporalResult(
                formula=label, ok=False,
                detail="no successor state",
            )
        ok = _safe_pred(formula.pred, trace[1])
        return TemporalResult(
            formula=label, ok=ok,
            witness_index=1 if ok else None,
            violation_index=None if ok else 1,
        )

    if isinstance(formula, Implies):
        # For every step where antecedent is true, consequent must
        # hold somewhere later (optionally within N steps).
        for i, ev in enumerate(trace):
            if not _safe_pred(formula.antecedent, ev):
                continue
            upper = len(trace)
            if formula.within is not None:
                upper = min(len(trace), i + int(formula.within) + 1)
            consequent_ok = False
            for j in range(i + 1, upper):
                if _safe_pred(formula.consequent, trace[j]):
                    consequent_ok = True
                    break
            if not consequent_ok:
                return TemporalResult(
                    formula=label, ok=False,
                    violation_index=i,
                    detail=(
                        f"antecedent at {i} without consequent "
                        f"within {formula.within or 'the rest of trace'}"
                    ),
                )
        return TemporalResult(
            formula=label, ok=True,
            detail="implication holds everywhere",
        )

    raise TypeError(f"unknown formula type {type(formula).__name__}")


def check_rules(
    trace: Iterable[dict[str, Any]],
    rules: Iterable[Formula],
) -> list[TemporalResult]:
    trace = list(trace)
    return [evaluate(rule, trace) for rule in rules]


# ── Helpers ────────────────────────────────────────────────

def _label(formula: Formula) -> str:
    name = getattr(formula, "name", "") or ""
    kind = type(formula).__name__.lower()
    return f"{kind}:{name}" if name else kind


def _safe_pred(pred: Predicate, ev: dict[str, Any]) -> bool:
    try:
        return bool(pred(ev))
    except Exception:
        return False


# ── Event helpers ──────────────────────────────────────────

def kind_is(kind: str) -> Predicate:
    return lambda ev: ev.get("kind") == kind


def kind_in(kinds: Iterable[str]) -> Predicate:
    accepted = set(kinds)
    return lambda ev: ev.get("kind") in accepted


def field_matches(field: str, value: Any) -> Predicate:
    return lambda ev: ev.get(field) == value


def all_of(*preds: Predicate) -> Predicate:
    return lambda ev: all(_safe_pred(p, ev) for p in preds)


def any_of(*preds: Predicate) -> Predicate:
    return lambda ev: any(_safe_pred(p, ev) for p in preds)
