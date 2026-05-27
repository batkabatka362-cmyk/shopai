"""Refund activity log (Wave 102).

The Wave 101 ``refund_applier`` issues refunds via Shopify
``refundCreate`` but the only artifact left behind was the
``record_writeback`` fan-out (MemoryIntelligence /
DataArchitecture / LearningLoop -- all three are decision-time
read sources, not operator-facing surfaces).

Operators need a direct surface: "how much money has the
autonomous loop refunded? was it the right call? are
adapter_failed skips piling up?"

Wave 102 ships a JSON-backed append log:
  ``data/refund_log.json`` -- bounded to 1000 entries (oldest
  rotated out). Same pattern as ``attribution_snapshots.json``
  (Wave 11) and ``plan_history.json``.

Pattern J guard: the recorder no-ops under ``PYTEST_CURRENT_TEST``
so tests don't pollute the production log.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_PATH = Path("data") / "refund_log.json"
_MAX_ENTRIES = 1000


@dataclass
class RefundLogEntry:
    return_id: str
    order_id: str
    store_id: str = ""
    refund_amount: float = 0.0
    status: str = ""           # recorded / adapter_failed / etc
    applied: bool = False
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def _is_test_environment() -> bool:
    """Pattern J: short-circuit under pytest so synthetic
    refund applies don't pollute the production log."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load() -> list[dict[str, Any]]:
    if not _LOG_PATH.exists():
        return []
    try:
        with _LOG_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return raw
    except Exception as exc:  # noqa: BLE001
        logger.debug("refund_log load raised: %s", exc)
    return []


def _save(entries: list[dict[str, Any]]) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Bound the file so it doesn't grow forever
        if len(entries) > _MAX_ENTRIES:
            entries = entries[-_MAX_ENTRIES:]
        with _LOG_PATH.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refund_log save raised: %s", exc)


def record_refund(entry: RefundLogEntry) -> None:
    """Append an entry to the refund log. No-op under pytest."""
    if _is_test_environment():
        return
    if not isinstance(entry, RefundLogEntry):
        return
    rows = _load()
    rows.append(asdict(entry))
    _save(rows)


def recent_refunds(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return refund log rows from the last ``window_hours``.

    Optional ``store_id`` filter scopes to one store. When None,
    all stores are returned.
    """
    cutoff = time.time() - max(0.0, window_hours) * 3600.0
    rows = _load()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = r.get("recorded_at")
        if not isinstance(ts, (int, float)) or ts < cutoff:
            continue
        if store_id and r.get("store_id") != store_id:
            continue
        out.append(r)
    # Newest first
    out.sort(
        key=lambda row: row.get("recorded_at", 0),
        reverse=True,
    )
    return out


def log_size() -> int:
    """Total rows in the log (useful for tests + dashboards)."""
    return len(_load())
