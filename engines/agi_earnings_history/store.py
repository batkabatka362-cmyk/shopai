"""Persistent JSON-backed earnings verdict log."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_PATH = Path("data/agi_earnings_history.json")
_MAX_ENTRIES = 5000

# W963-91: ladder hoisted to core.agi.verdict_vocabulary.
from core.agi.verdict_vocabulary import VERDICT_RANK as _VERDICT_RANK


def _is_test_environment() -> bool:
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> list[dict[str, Any]]:
    if not _DATA_PATH.exists():
        return []
    try:
        with _DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except (
        OSError, json.JSONDecodeError,
    ) as exc:
        logger.debug(
            "earnings_history: load raised: %s", exc,
        )
    return []


def _atomic_write(entries: list[dict[str, Any]]) -> bool:
    try:
        _DATA_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
        fd, tmp = tempfile.mkstemp(
            prefix=".agi_earnings_history.",
            suffix=".json",
            dir=str(_DATA_PATH.parent),
        )
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
        os.replace(tmp, str(_DATA_PATH))
        return True
    except OSError as exc:
        logger.debug(
            "earnings_history: write raised: %s", exc,
        )
        return False


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
