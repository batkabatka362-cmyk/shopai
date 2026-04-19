"""Abstraction ladder — move rules between specific and general.

Rules arrive at two natural heights:

  Specific:   "kill audio launches with ROAS < 1.5 after 3 days"
  General:    "kill any niche's launches below its own kill-threshold"

Humans move fluidly up and down this ladder — the specific form is
easier to apply, the general form is easier to *teach*. ShopAI had
no mechanism for it, so every pattern hardened at whatever height
it was first codified.

AbstractionLadder offers three operations:

  generalise(rule)    — replace a concrete value with a parameter
                         referencing a lookup table. Height + 1.
  specialise(rule, bindings) — substitute parameters back to
                                concrete values. Height − 1.
  climb(rules)        — find a set of specific rules that share a
                         structural template and return one abstract
                         rule that subsumes them.

Rule structure (simple dict form so it integrates with existing
rule tables without a new schema):

    {
        "id": "...",
        "when": {"niche": "audio", "roas_lt": 1.5,
                  "days_since_launch_gt": 3},
        "then": {"action": "kill"},
        "height": 0,               # lower = more specific
        "parameters": {}           # filled in by generalise
    }

Pure Python, zero LLM. Cheap to call on every rule every cycle.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AbstractionReport:
    kind: str                       # "generalise" | "specialise" | "climb"
    before: dict[str, Any]
    after: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "before": self.before,
            "after": self.after,
            "notes": self.notes,
        }


# ── Primitives ──────────────────────────────────────────────

def generalise(
    rule: dict[str, Any], parameters: dict[str, str],
) -> AbstractionReport:
    """Replace concrete values in ``rule['when']`` with named
    parameters.

    ``parameters`` maps ``(field, concrete_value)`` → parameter name,
    e.g. ``{"niche:audio": "$niche", "roas_lt:1.5": "$kill_threshold"}``.
    """
    before = _copy(rule)
    new_when: dict[str, Any] = {}
    used_params: dict[str, Any] = {}
    for k, v in rule.get("when", {}).items():
        key = f"{k}:{v}"
        if key in parameters:
            param = parameters[key]
            new_when[k] = param
            used_params[param] = v
        else:
            new_when[k] = v
    after = _copy(rule)
    after["when"] = new_when
    after["parameters"] = {**rule.get("parameters", {}), **used_params}
    after["height"] = int(rule.get("height", 0)) + 1
    return AbstractionReport(
        kind="generalise",
        before=before, after=after,
        notes=[f"introduced {len(used_params)} parameter(s)"],
    )


def specialise(
    rule: dict[str, Any], bindings: dict[str, Any],
) -> AbstractionReport:
    """Substitute parameters in a rule's ``when`` clause with
    concrete values. ``bindings`` maps parameter name (``$niche``)
    → concrete value."""
    before = _copy(rule)
    new_when: dict[str, Any] = {}
    for k, v in rule.get("when", {}).items():
        if isinstance(v, str) and v.startswith("$") and v in bindings:
            new_when[k] = bindings[v]
        else:
            new_when[k] = v
    params = dict(rule.get("parameters", {}))
    for b in bindings:
        params.pop(b, None)
    after = _copy(rule)
    after["when"] = new_when
    after["parameters"] = params
    after["height"] = max(0, int(rule.get("height", 0)) - 1)
    return AbstractionReport(
        kind="specialise",
        before=before, after=after,
        notes=[f"bound {len(bindings)} parameter(s)"],
    )


def climb(rules: list[dict[str, Any]]) -> AbstractionReport | None:
    """Given several specific rules that share the same ``when``
    *keys* and same ``then`` action but differ on at least one
    value, emit one abstract rule that subsumes them.

    Returns None if no climbable cluster exists (fewer than 2
    matching rules, or keys/actions differ)."""
    if len(rules) < 2:
        return None
    # All rules must have the same set of when keys and same action
    when_keys = {frozenset(r.get("when", {}).keys()) for r in rules}
    actions = {_action_of(r) for r in rules}
    if len(when_keys) != 1 or len(actions) != 1:
        return None
    shared_keys = list(next(iter(when_keys)))
    # Find fields where rules differ — those become parameters
    differing: list[str] = []
    for key in shared_keys:
        vals = {r["when"][key] for r in rules}
        if len(vals) > 1:
            differing.append(key)
    if not differing:
        return None
    # Build abstract rule
    param_names = {k: f"${k}" for k in differing}
    abstract_when: dict[str, Any] = {}
    for key in shared_keys:
        if key in param_names:
            abstract_when[key] = param_names[key]
        else:
            abstract_when[key] = rules[0]["when"][key]
    abstract_rule = {
        "id": f"abstract:{'+'.join(sorted(differing))}",
        "when": abstract_when,
        "then": rules[0].get("then", {}),
        "height": max(int(r.get("height", 0)) for r in rules) + 1,
        "parameters": {p: None for p in param_names.values()},
        "source_rules": [r.get("id") for r in rules if r.get("id")],
    }
    return AbstractionReport(
        kind="climb",
        before={"rule_count": len(rules), "example": rules[0]},
        after=abstract_rule,
        notes=[f"parametrised {len(differing)} field(s): "
               f"{', '.join(sorted(differing))}"],
    )


# ── Cluster helpers ─────────────────────────────────────────

def cluster_climbable(
    rules: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group rules by shared structural signature so ``climb`` can
    run per cluster. Two rules share a signature iff their
    ``when`` keys and action are identical."""
    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for r in rules:
        keys = tuple(sorted(r.get("when", {}).keys()))
        sig = (keys, _action_of(r))
        buckets.setdefault(sig, []).append(r)
    return [grp for grp in buckets.values() if len(grp) >= 2]


# ── Internals ──────────────────────────────────────────────

def _action_of(rule: dict[str, Any]) -> str:
    return str(rule.get("then", {}).get("action", ""))


def _copy(rule: dict[str, Any]) -> dict[str, Any]:
    import copy
    return copy.deepcopy(rule)
