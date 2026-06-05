"""JSON-backed strategist memory.

Shape:
  {
    "entries": [
      {
        "ts": <unix_seconds>,
        "store_id": "...",
        "signal": "funnel",
        "action": "Run CRO variants",
        "drill_command": "shopai cro variants",
        "confidence": 0.85,
        "impact": "high",
        "priority_score": 0.85,
        "outcome": "positive" | "negative" | "unknown",
        "outcome_recorded_at": <unix_seconds | null>,
        "notes": "...",
      },
      ...
    ]
  }

Bounded to last 2000 entries (rolling).

Pattern J test guard so unit tests don't pollute prod state.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

# W963-92: canonical persistence helpers
from core.agi.persistence import (
    atomic_write_json,
    is_test_environment as _is_test_environment,
    load_json_dict as _load_json_dict,
)

logger = logging.getLogger(__name__)


_PATH = Path(
    os.environ.get(
        "SHOPAI_STRATEGIST_MEMORY_PATH",
        "data/strategist_memory.json",
    )
)

_MAX_ENTRIES = 2000


def _load_raw() -> dict[str, Any]:
    """Load + normalize: ensure 'entries' key always
    exists as a list."""
    data = _load_json_dict(_PATH)
    if "entries" not in data or not isinstance(
        data.get("entries"), list,
    ):
        data["entries"] = []
    return data


def _atomic_write(data: dict[str, Any]) -> None:
    atomic_write_json(_PATH, data)


def record(
    *,
    store_id: str,
    signal: str,
    action: str,
    drill_command: str = "",
    confidence: float = 0.0,
    impact: str = "medium",
    priority_score: float = 0.0,
    outcome: str = "unknown",
    notes: str = "",
) -> bool:
    """Append an entry. Returns True on write, False on
    test-env / I/O error / invalid input."""
    if _is_test_environment():
        return False
    if not store_id or not signal or not action:
        return False
    raw = _load_raw()
    entries = raw.setdefault("entries", [])
    entries.append({
        "ts": time.time(),
        "store_id": str(store_id),
        "signal": str(signal),
        "action": str(action),
        "drill_command": str(drill_command),
        "confidence": float(confidence or 0.0),
        "impact": str(impact),
        "priority_score": float(priority_score or 0.0),
        "outcome": str(outcome or "unknown"),
        "outcome_recorded_at": None,
        "notes": str(notes or ""),
    })
    # Bound rolling
    if len(entries) > _MAX_ENTRIES:
        del entries[: len(entries) - _MAX_ENTRIES]
    _atomic_write(raw)
    return True


def recall(
    *,
    store_id: str = "",
    signal: str = "",
    k: int = 10,
) -> list[dict[str, Any]]:
    """Return the last K entries matching store+signal filters.
    Empty store/signal means no filter."""
    raw = _load_raw()
    entries = list(raw.get("entries") or [])
    filtered = []
    for e in reversed(entries):
        if (
            store_id and str(e.get("store_id")) != store_id
        ):
            continue
        if signal and str(e.get("signal")) != signal:
            continue
        filtered.append(e)
        if len(filtered) >= max(1, k):
            break
    return filtered


def signal_stats(
    *,
    store_id: str = "",
    signal: str = "",
) -> dict[str, int]:
    """Return {positive, negative, unknown, total} counts."""
    raw = _load_raw()
    out = {
        "positive": 0,
        "negative": 0,
        "unknown": 0,
        "total": 0,
    }
    for e in raw.get("entries") or []:
        if (
            store_id and str(e.get("store_id")) != store_id
        ):
            continue
        if signal and str(e.get("signal")) != signal:
            continue
        outcome = str(e.get("outcome") or "unknown")
        if outcome in ("positive", "negative", "unknown"):
            out[outcome] += 1
        out["total"] += 1
    return out


def update_outcome(
    *,
    entry_index: int,
    outcome: str,
) -> bool:
    """Update an entry's outcome (positive / negative).
    Returns True on write."""
    if _is_test_environment():
        return False
    if outcome not in ("positive", "negative", "unknown"):
        return False
    raw = _load_raw()
    entries = raw.get("entries") or []
    if entry_index < 0 or entry_index >= len(entries):
        return False
    entries[entry_index]["outcome"] = outcome
    entries[entry_index]["outcome_recorded_at"] = (
        time.time()
    )
    _atomic_write(raw)
    return True


def entry_count() -> int:
    """Total entries currently stored."""
    return len(_load_raw().get("entries") or [])


def stores_with_entries() -> list[str]:
    """Distinct store_ids with at least one entry."""
    raw = _load_raw()
    seen: list[str] = []
    for e in raw.get("entries") or []:
        sid = str(e.get("store_id") or "")
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def reset_path(path: Path) -> None:
    """Test-only hook to override the persistence path."""
    global _PATH
    _PATH = path
