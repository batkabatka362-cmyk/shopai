"""Safety envelope — bounded action space per context.

ethics_gate (v8-D5) inspects one outbound action at a time and
blocks if it crosses a line. The safety envelope complements that
by defining the *allowed* action space *upfront*: for a given
context, what are the valid ranges the planner / MCTS / curiosity
policy may even propose?

Without an envelope, the planner can suggest $1000/day ad spend
when cash is tight, or propose a 99% discount on a premium
product. ethics_gate would catch some of these post-hoc, but
bounding the search space upfront is cheaper and safer — the
planner never explores obviously-bad regions.

An Envelope carries per-field bounds:

  • numeric_ranges  {field: (min, max)}
  • allowed_values  {field: set_of_values}
  • forbidden_fields {field_name, ...}     # never present

Envelopes compose via ``intersect`` so a cycle can stack a global
envelope (owner-configured spend caps) with a context-specific
envelope (low cash → tighter limits).

APIs:

  envelope_for(context) → Envelope    (registered rule → matches)
  Envelope.admits(action)              → bool
  Envelope.project(action)             → clamped action that fits
  register_rule(predicate, envelope_builder)
      → when predicate(context) holds, the builder's envelope is
        contributed to the intersection

Zero LLM, pure Python, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class Envelope:
    numeric_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    allowed_values: dict[str, frozenset[Any]] = field(default_factory=dict)
    forbidden_fields: frozenset[str] = field(default_factory=frozenset)
    description: str = ""

    # ── Predicate ───────────────────────────────────────────

    def admits(self, action: dict[str, Any]) -> bool:
        for fld in self.forbidden_fields:
            if fld in action:
                return False
        for fld, (lo, hi) in self.numeric_ranges.items():
            if fld not in action:
                continue
            try:
                v = float(action[fld])
            except (TypeError, ValueError):
                return False
            if not (lo <= v <= hi):
                return False
        for fld, allowed in self.allowed_values.items():
            if fld not in action:
                continue
            if action[fld] not in allowed:
                return False
        return True

    # ── Projection ─────────────────────────────────────────

    def project(self, action: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of ``action`` clamped to the envelope."""
        out = dict(action)
        for fld in self.forbidden_fields:
            out.pop(fld, None)
        for fld, (lo, hi) in self.numeric_ranges.items():
            if fld not in out:
                continue
            try:
                v = float(out[fld])
            except (TypeError, ValueError):
                out.pop(fld, None)
                continue
            out[fld] = max(lo, min(hi, v))
        for fld, allowed in self.allowed_values.items():
            if fld not in out:
                continue
            if out[fld] not in allowed:
                # Pick closest literal if numeric, else first allowed
                if allowed and all(isinstance(x, (int, float)) for x in allowed):
                    try:
                        v = float(out[fld])
                        closest = min(allowed, key=lambda x: abs(float(x) - v))
                        out[fld] = closest
                    except (TypeError, ValueError):
                        out[fld] = next(iter(allowed))
                elif allowed:
                    out[fld] = next(iter(allowed))
        return out

    # ── Composition ────────────────────────────────────────

    def intersect(self, other: "Envelope") -> "Envelope":
        """Intersect two envelopes — union of forbids, intersect of
        ranges, intersect of allowed values. The result is stricter
        than either input."""
        # Numeric ranges: take tighter bounds
        numeric: dict[str, tuple[float, float]] = dict(self.numeric_ranges)
        for fld, (lo, hi) in other.numeric_ranges.items():
            if fld in numeric:
                a, b = numeric[fld]
                numeric[fld] = (max(a, lo), min(b, hi))
            else:
                numeric[fld] = (lo, hi)
        # Allowed values: intersect; if a field exists only on one
        # side, keep that side's set.
        allowed: dict[str, frozenset[Any]] = dict(self.allowed_values)
        for fld, vals in other.allowed_values.items():
            if fld in allowed:
                allowed[fld] = allowed[fld] & vals
            else:
                allowed[fld] = vals
        return Envelope(
            numeric_ranges=numeric,
            allowed_values=allowed,
            forbidden_fields=self.forbidden_fields | other.forbidden_fields,
            description=(
                f"({self.description}) ∩ ({other.description})"
                if self.description and other.description
                else self.description or other.description
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "numeric_ranges": {
                k: list(v) for k, v in self.numeric_ranges.items()
            },
            "allowed_values": {
                k: sorted(map(str, v))
                for k, v in self.allowed_values.items()
            },
            "forbidden_fields": sorted(self.forbidden_fields),
            "description": self.description,
        }


# ── Context-specific registry ───────────────────────────────

EnvBuilder = Callable[[dict[str, Any]], Envelope]
Predicate = Callable[[dict[str, Any]], bool]

_RULES: list[tuple[Predicate, EnvBuilder]] = []


def register_rule(predicate: Predicate, builder: EnvBuilder) -> None:
    _RULES.append((predicate, builder))


def clear_rules() -> None:
    _RULES.clear()


def envelope_for(
    context: dict[str, Any], base: Envelope | None = None,
) -> Envelope:
    """Compose every matching rule's envelope into a single tight
    envelope. ``base`` is an optional global envelope that applies
    to every context."""
    env = base or Envelope()
    for pred, builder in _RULES:
        try:
            if pred(context):
                env = env.intersect(builder(context))
        except Exception:
            # Rule errors must not break envelope computation.
            continue
    return env


# ── Convenience defaults ────────────────────────────────────

def default_global_envelope(
    max_daily_spend_usd: float = 500.0,
    max_price_usd: float = 5_000.0,
    allowed_currencies: Iterable[str] = ("USD", "EUR", "GBP"),
) -> Envelope:
    return Envelope(
        numeric_ranges={
            "daily_spend_usd": (0.0, float(max_daily_spend_usd)),
            "price_usd": (0.0, float(max_price_usd)),
            "discount_pct": (0.0, 70.0),
        },
        allowed_values={
            "currency": frozenset(allowed_currencies),
        },
        description="default global envelope",
    )
