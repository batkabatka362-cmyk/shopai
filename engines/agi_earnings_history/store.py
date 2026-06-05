"""Persistent JSON-backed earnings verdict log."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

# W963-91+92: canonical vocabulary + persistence helpers
from core.agi.persistence import (
    atomic_write_json,
    is_test_environment as _is_test_environment,
    load_json_list as _load_json_list,
)
from core.agi.verdict_vocabulary import VERDICT_RANK as _VERDICT_RANK

logger = logging.getLogger(__name__)

_DATA_PATH = Path("data/agi_earnings_history.json")
_MAX_ENTRIES = 5000


def _load_raw() -> list[dict[str, Any]]:
    return _load_json_list(_DATA_PATH)


def _atomic_write(entries: list[dict[str, Any]]) -> bool:
    return atomic_write_json(_DATA_PATH, entries)


def record_snapshot(snapshot: dict[str, Any]) -> bool:
    """Append one snapshot; bounded to _MAX_ENTRIES."""
    if _is_test_environment():
        return False
    if not isinstance(snapshot, dict):
        return False
    entries = _load_raw()
    enriched = {
        "ts": float(snapshot.get("ts") or time.time()),
        **{
            k: v for k, v in snapshot.items() if k != "ts"
        },
    }
    entries.append(enriched)
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    return _atomic_write(entries)


def snapshot_count() -> int:
    return len(_load_raw())


def query(*, days: int = 30, limit: int = 100) -> list[
    dict[str, Any]
]:
    """Newest-first within window."""
    cutoff = time.time() - (max(1, days) * 86400.0)
    entries = _load_raw()
    filtered = [
        e for e in entries
        if float(e.get("ts", 0) or 0) >= cutoff
    ]
    filtered.sort(
        key=lambda e: float(e.get("ts", 0) or 0),
        reverse=True,
    )
    return filtered[:max(1, limit)]


def compute_trend(*, days: int = 14) -> dict[str, Any]:
    """First-half vs second-half rank-avg comparison."""
    snaps = query(days=days, limit=500)
    if len(snaps) < 2:
        return {
            "days": days,
            "sample_count": len(snaps),
            "verdict": "no_data",
            "first_avg_rank": 0.0,
            "second_avg_rank": 0.0,
            "delta": 0.0,
        }
    # Sort oldest-first for trend
    snaps.sort(key=lambda e: float(e.get("ts", 0) or 0))
    half = len(snaps) // 2
    if half == 0:
        half = 1
    first = snaps[:half]
    second = snaps[half:]
    first_avg = (
        sum(_VERDICT_RANK.get(
            str(e.get("verdict") or "no_data"), 0,
        ) for e in first) / len(first)
    )
    second_avg = (
        sum(_VERDICT_RANK.get(
            str(e.get("verdict") or "no_data"), 0,
        ) for e in second) / len(second)
    )
    delta = round(second_avg - first_avg, 2)
    if delta > 0.5:
        verdict = "improving"
    elif delta < -0.5:
        verdict = "declining"
    else:
        verdict = "flat"
    return {
        "days": days,
        "sample_count": len(snaps),
        "verdict": verdict,
        "first_avg_rank": round(first_avg, 2),
        "second_avg_rank": round(second_avg, 2),
        "delta": delta,
    }


def latest() -> dict[str, Any] | None:
    snaps = query(days=365, limit=1)
    return snaps[0] if snaps else None
