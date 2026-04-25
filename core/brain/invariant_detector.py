"""Invariant detector — find facts that hold across every case.

Brain learning so far surfaces *patterns* (common, not universal).
Invariants are the stronger claim: properties that hold *always*.
Once codified they become hard checks — the brain refuses to
ship a decision that would violate them, and they cost zero to
verify.

Examples:

  • "Every published product has margin_pct > 0"
  • "Every launch in our top-performing niche uses friendly tone"
  • "Every refund order arrived after shipping delay > 5 days"

InvariantDetector scans a batch of observations and finds:

  • Equality invariants — a field always has the same value.
  • Range invariants — a numeric field always lies within a
    bounded [lo, hi].
  • Implication invariants — "when X=a, Y is always in {...}".
  • Non-null invariants — a field is never absent.

Each invariant carries a ``confidence`` based on sample size and
a ``violation`` counter so the owner digest can surface "this
invariant held for 847 cases, just broke in case #848".

Pure Python, zero LLM.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Invariant:
    kind: str                    # "equality" | "range" | "implication" | "non_null"
    field: str
    constant: Any = None
    lo: float | None = None
    hi: float | None = None
    given_field: str | None = None
    given_value: Any = None
    allowed_values: frozenset[Any] = field(default_factory=frozenset)
    sample_size: int = 0
    violations: int = 0

    @property
    def confidence(self) -> float:
        if self.sample_size == 0:
            return 0.0
        # 1 - violations/n, squashed by sqrt(n) for small-sample
        # penalty so n=3 is less confident than n=300.
        import math
        base = 1.0 - self.violations / self.sample_size
        return round(base * min(1.0, math.sqrt(self.sample_size) / 20),
                     3)

    def describe(self) -> str:
        if self.kind == "equality":
            return f"{self.field} is always {self.constant!r}"
        if self.kind == "range":
            return (f"{self.field} is always within "
                    f"[{self.lo}, {self.hi}]")
        if self.kind == "implication":
            allowed = ", ".join(sorted(map(repr, self.allowed_values)))
            return (f"when {self.given_field}={self.given_value!r}, "
                    f"{self.field} ∈ {{{allowed}}}")
        if self.kind == "non_null":
            return f"{self.field} is always present"
        return "unknown invariant"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "field": self.field,
            "constant": self.constant,
            "lo": self.lo, "hi": self.hi,
            "given_field": self.given_field,
            "given_value": self.given_value,
            "allowed_values": sorted(map(str, self.allowed_values)),
            "sample_size": self.sample_size,
            "violations": self.violations,
            "confidence": self.confidence,
            "describe": self.describe(),
        }


# ── Detection passes ────────────────────────────────────────

def _coerce_numeric(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _equality(
    rows: list[dict[str, Any]], field_: str,
) -> Invariant | None:
    values: set[Any] = set()
    for r in rows:
        if field_ in r:
            values.add(r[field_])
    if len(values) == 1:
        return Invariant(
            kind="equality", field=field_,
            constant=next(iter(values)),
            sample_size=len(rows),
        )
    return None


def _range(
    rows: list[dict[str, Any]], field_: str,
) -> Invariant | None:
    lo = float("inf")
    hi = float("-inf")
    n = 0
    for r in rows:
        v = _coerce_numeric(r.get(field_))
        if v is None:
            continue
        n += 1
        lo = min(lo, v)
        hi = max(hi, v)
    if n == 0 or not (lo <= hi):
        return None
    if lo == hi:
        return None   # caught by equality
    return Invariant(
        kind="range", field=field_,
        lo=lo, hi=hi, sample_size=n,
    )


def _non_null(
    rows: list[dict[str, Any]], field_: str,
) -> Invariant | None:
    missing = sum(
        1 for r in rows
        if field_ not in r or r[field_] is None or r[field_] == ""
    )
    if missing > 0:
        return None
    return Invariant(
        kind="non_null", field=field_, sample_size=len(rows),
    )


def _implication(
    rows: list[dict[str, Any]],
    given_field: str, target_field: str,
) -> list[Invariant]:
    groups: dict[Any, set[Any]] = defaultdict(set)
    counts: dict[Any, int] = defaultdict(int)
    for r in rows:
        if given_field not in r or target_field not in r:
            continue
        gv = r[given_field]
        tv = r[target_field]
        groups[gv].add(tv)
        counts[gv] += 1
    out: list[Invariant] = []
    for gv, tvs in groups.items():
        if counts[gv] < 3:
            continue
        # Only emit when the target set is small (∣tvs∣ ≤ 3)
        if len(tvs) <= 3:
            out.append(Invariant(
                kind="implication",
                field=target_field,
                given_field=given_field,
                given_value=gv,
                allowed_values=frozenset(tvs),
                sample_size=counts[gv],
            ))
    return out


# ── Detector ───────────────────────────────────────────────

def detect(
    rows: Iterable[dict[str, Any]],
    *,
    fields: Iterable[str] | None = None,
    implication_pairs: Iterable[tuple[str, str]] | None = None,
    min_sample: int = 3,
) -> list[Invariant]:
    rows = list(rows)
    if len(rows) < min_sample:
        return []
    # Union of all fields seen
    all_fields: set[str] = set()
    for r in rows:
        all_fields.update(r.keys())
    target_fields = list(fields) if fields is not None else sorted(all_fields)

    out: list[Invariant] = []
    for f in target_fields:
        inv = _equality(rows, f)
        if inv is not None:
            out.append(inv)
            continue
        inv = _range(rows, f)
        if inv is not None:
            out.append(inv)
        non_null_inv = _non_null(rows, f)
        if non_null_inv is not None:
            out.append(non_null_inv)

    if implication_pairs:
        for g, t in implication_pairs:
            out.extend(_implication(rows, g, t))

    return out


# ── Verifier ───────────────────────────────────────────────

def check(
    invariant: Invariant, row: dict[str, Any],
) -> bool:
    """True iff the row satisfies the invariant."""
    if invariant.kind == "equality":
        return row.get(invariant.field) == invariant.constant
    if invariant.kind == "range":
        v = _coerce_numeric(row.get(invariant.field))
        if v is None:
            return False
        return invariant.lo <= v <= invariant.hi
    if invariant.kind == "non_null":
        v = row.get(invariant.field)
        return v is not None and v != ""
    if invariant.kind == "implication":
        if row.get(invariant.given_field) != invariant.given_value:
            return True           # premise fails → implication holds
        return row.get(invariant.field) in invariant.allowed_values
    return True


def sweep(
    invariants: Iterable[Invariant],
    row: dict[str, Any],
) -> list[Invariant]:
    """Return invariants the row violates (could be empty)."""
    return [inv for inv in invariants if not check(inv, row)]
