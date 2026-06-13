"""W963-118: per-store cost attribution substrate.

EVERY adapter call gets attributed to a store_id (or
fleet when active_store unset) + recorded in an
append-only event log. Downstream substrate (quota
tracking, autopause, per-store ROAS) reads from the
same log -- single source of truth for "what did this
store cost us today?"

Storage: JSONL append-only file at
``data/per_store_costs.jsonl``. Rotates to
``.archive.jsonl`` when it exceeds 5MB; rotation
preserves the active log's most recent entries.

Performance contract:
  * record_call() runs in O(1) under a re-entrant lock
    + a single file append (no full-file read).
  * Backward compat: failures to record are swallowed
    silently so they never break adapter calls.
  * Pattern J: short-circuits under pytest so tests
    don't pollute production cost logs.
"""
from .flow import PerStoreCostsEngine
from .recorder import (
    CostEvent,
    record_call,
    rotate_if_needed,
)
from .query import (
    costs_by_adapter,
    costs_by_store,
    costs_total,
    get_recent_events,
)

__all__ = [
    "PerStoreCostsEngine",
    "CostEvent",
    "record_call",
    "rotate_if_needed",
    "costs_by_adapter",
    "costs_by_store",
    "costs_total",
    "get_recent_events",
]
