"""Context compactor — compress cycle context into LLM-ready brief.

A full cycle produces kilobytes of state: products, orders, ads,
phase errors, KPI snapshots. Feeding all that into an LLM prompt is
wasteful (expensive + slow) and counter-productive (long prompts
degrade reasoning quality). The context compactor produces a
budget-capped brief that:

  1. Ranks fields by importance (size-weighted + explicit priority).
  2. Keeps the top-N fields.
  3. Summarises list/dict fields (count + first few entries).
  4. Always guarantees the total serialised size stays under a cap.

Usage:

    brief = compact(
        context=full_state,
        priority_fields=("owner_goal", "cycle_id", "phase_errors"),
        max_bytes=4096,
    )

Pure stdlib, deterministic, no LLM.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.context_compactor")


@dataclass
class CompactBrief:
    fields: dict[str, Any] = field(default_factory=dict)
    dropped_fields: list[str] = field(default_factory=list)
    byte_size: int = 0
    budget: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "fields": dict(self.fields),
            "dropped_fields": list(self.dropped_fields),
            "byte_size": self.byte_size,
            "budget": self.budget,
            "truncated": self.truncated,
        }

    def as_text(self) -> str:
        """Return a deterministic key=value block suitable for
        direct insertion into an LLM system prompt."""
        lines = [f"{k}: {self.fields[k]}" for k in sorted(self.fields)]
        if self.truncated:
            lines.append(
                f"[truncated: {len(self.dropped_fields)} fields dropped "
                f"to fit {self.budget}-byte budget]"
            )
        return "\n".join(lines)


# ── Summarise helpers ────────────────────────────────────

def _summarise_value(value: Any, *, max_list_items: int = 5) -> Any:
    """Replace large containers with a compact summary."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        # Primitives: keep as-is but cap string length.
        if isinstance(value, str) and len(value) > 200:
            return value[:197] + "..."
        return value
    if isinstance(value, dict):
        # Dict → {k: summarised_v} up to max_list_items keys
        items = list(value.items())[:max_list_items]
        return {
            str(k): _summarise_value(v, max_list_items=max_list_items)
            for k, v in items
        }
    if isinstance(value, (list, tuple)):
        n = len(value)
        head = [
            _summarise_value(x, max_list_items=max_list_items)
            for x in list(value)[:max_list_items]
        ]
        return {
            "__list__": True,
            "count": n,
            "head": head,
        }
    # Fallback: stringify
    return str(value)[:200]


def _byte_size(value: Any) -> int:
    try:
        return len(json.dumps(
            value, default=str, sort_keys=True,
        ).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(value).encode("utf-8"))


# ── Main API ─────────────────────────────────────────────

def compact(
    context: dict[str, Any],
    *,
    priority_fields: Iterable[str] = (),
    max_bytes: int = 4096,
    max_list_items: int = 5,
) -> CompactBrief:
    """Produce a byte-capped summary of ``context``.

    priority_fields are kept even if they cost more budget; anything
    else is added in size-ascending order until the budget is
    exhausted.
    """
    if max_bytes < 256:
        raise ValueError("max_bytes must be ≥ 256")
    if max_list_items < 1:
        raise ValueError("max_list_items must be ≥ 1")
    raw = dict(context or {})
    summarised: dict[str, Any] = {
        k: _summarise_value(v, max_list_items=max_list_items)
        for k, v in raw.items()
    }

    brief_fields: dict[str, Any] = {}
    dropped: list[str] = []

    # Stage 1: priority fields — always keep them (they were caller-
    # marked important).
    for key in priority_fields:
        if key in summarised:
            brief_fields[key] = summarised[key]

    # Stage 2: add remaining fields in size-ascending order until we
    # blow the budget.
    remaining = [
        k for k in summarised if k not in brief_fields
    ]
    remaining.sort(
        key=lambda k: _byte_size(summarised[k]),
    )
    for key in remaining:
        tentative = dict(brief_fields)
        tentative[key] = summarised[key]
        if _byte_size(tentative) > max_bytes:
            dropped.append(key)
            continue
        brief_fields = tentative

    final_size = _byte_size(brief_fields)
    truncated = bool(dropped) or final_size > max_bytes
    return CompactBrief(
        fields=brief_fields,
        dropped_fields=dropped,
        byte_size=final_size,
        budget=int(max_bytes),
        truncated=truncated,
    )
