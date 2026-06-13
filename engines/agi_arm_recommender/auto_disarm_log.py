"""Persistent log of W963-82 auto-disarm events.

Each cycle when SHOPAI_AUTO_DISARM_ON_OVERRIDE fires the
auto-disarm bridge, we want to record:
  - WHEN it fired (timestamp)
  - WHY (which override reason)
  - WHAT got disarmed (which autonomy domains)
  - WHICH engine recommendations drove it

Operator scaling to 20 stores needs this audit trail to
debug "why did the marketing domain pause yesterday?"
without grepping logs.

JSON-backed at data/auto_disarm_log.json. Bounded to 2000
entries (newer pushes older off). Atomic write via
tempfile + os.replace.

Pattern J guard: short-circuits under pytest unless
SHOPAI_FORCE_PRODUCTION_WRITES=1.

Public API:
  record_event(reason, domains, engines)
  recent_events(limit, hours)
  entry_count()
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# W963-92: canonical persistence helpers
from core.agi.persistence import (
    atomic_write_json,
    is_test_environment as _is_test_environment,
    load_json_list as _load_json_list,
)

logger = logging.getLogger(__name__)

_DATA_PATH = Path("data/auto_disarm_log.json")
_MAX_ENTRIES = 2000


@dataclass
class AutoDisarmEvent:
    ts: float
    override_reason: str
    domains_disarmed: list[str] = field(
        default_factory=list,
    )
    engines_recommended: list[str] = field(
        default_factory=list,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "override_reason": self.override_reason,
            "domains_disarmed": list(self.domains_disarmed),
            "engines_recommended": list(
                self.engines_recommended,
            ),
        }


# W963-92: _is_test_environment + load/write delegated to
# core.agi.persistence. _load_raw + _atomic_write kept as
# thin no-arg / single-arg wrappers so existing call sites
# AND test fixtures (which monkeypatch _DATA_PATH) keep
# working unchanged.


def _load_raw() -> list[dict[str, Any]]:
    return _load_json_list(_DATA_PATH)


def _atomic_write(entries: list[dict[str, Any]]) -> bool:
    return atomic_write_json(_DATA_PATH, entries)


def record_event(
    *,
    override_reason: str,
    domains_disarmed: list[str],
    engines_recommended: list[str] | None = None,
) -> bool:
    """Append one auto-disarm event. Pattern J guarded."""
    if _is_test_environment():
        return False
    if not override_reason:
        return False
    if not domains_disarmed:
        # Nothing got disarmed -- nothing to record.
        return False
    entries = _load_raw()
    event = AutoDisarmEvent(
        ts=time.time(),
        override_reason=str(override_reason),
        domains_disarmed=[
            str(d) for d in domains_disarmed
        ],
        engines_recommended=[
            str(e) for e in (engines_recommended or [])
        ],
    )
    entries.append(event.to_dict())
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    return _atomic_write(entries)


def recent_events(
    *,
    limit: int = 50,
    hours: float = 168.0,
) -> list[dict[str, Any]]:
    """Newest-first within window."""
    cutoff = time.time() - max(0.0, float(hours)) * 3600.0
    entries = _load_raw()
    filtered = [
        e for e in entries
        if float(e.get("ts", 0) or 0) >= cutoff
    ]
    filtered.sort(
        key=lambda e: float(e.get("ts", 0) or 0),
        reverse=True,
    )
    return filtered[:max(1, int(limit))]


def entry_count() -> int:
    return len(_load_raw())


def latest_event() -> dict[str, Any] | None:
    rows = recent_events(limit=1, hours=24 * 365)
    return rows[0] if rows else None
