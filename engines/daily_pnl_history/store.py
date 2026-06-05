"""JSON-backed persistent daily P&L history.

Shape:
  {
    "snapshots": [
      {
        "ts": <unix_seconds>,
        "date": "YYYY-MM-DD",
        "store_id": "...",
        "window_days": 7,
        "gross_revenue": 0.0,
        "refunds": 0.0,
        "net_revenue": 0.0,
        "ad_spend": 0.0,
        "esp_spend": 0.0,
        "shipping_cost": 0.0,
        "total_cost": 0.0,
        "gross_profit": 0.0,
        "margin_pct": 0.0,
        "order_count": 0,
        "verdict": "..."
      },
      ...
    ]
  }

Bounded to last 5000 snapshots.

Pattern J test guard + SHOPAI_FORCE_PRODUCTION_WRITES override.
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
        "SHOPAI_DAILY_PNL_HISTORY_PATH",
        "data/daily_pnl_history.json",
    )
)


_MAX_SNAPSHOTS = 5000


def _load_raw() -> dict[str, Any]:
    data = _load_json_dict(_PATH)
    if "snapshots" not in data or not isinstance(
        data.get("snapshots"), list,
    ):
        data["snapshots"] = []
    return data


def _atomic_write(data: dict[str, Any]) -> None:
    atomic_write_json(_PATH, data)


def record_snapshot(snapshot: dict[str, Any]) -> bool:
    """Append a snapshot. Returns True on write, False on
    test-env / invalid / I/O error."""
    if _is_test_environment():
        return False
    if not isinstance(snapshot, dict):
        return False
    if not snapshot.get("store_id"):
        return False
    raw = _load_raw()
    entries = raw.setdefault("snapshots", [])
    # Tag with timestamp + ISO date if not present
    if "ts" not in snapshot:
        snapshot["ts"] = time.time()
    if "date" not in snapshot:
        snapshot["date"] = time.strftime(
            "%Y-%m-%d", time.gmtime(snapshot["ts"]),
        )
    entries.append(snapshot)
    if len(entries) > _MAX_SNAPSHOTS:
        del entries[: len(entries) - _MAX_SNAPSHOTS]
    _atomic_write(raw)
    return True


def query(
    *,
    store_id: str = "",
    days: int = 30,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Return snapshots within window matching store_id. Empty
    store_id returns all stores. Newest first by ts.

    Sorts explicitly rather than assuming insertion order so
    out-of-order inserts (chaos / backfill / merging two
    history files) still return correctly."""
    raw = _load_raw()
    snapshots = raw.get("snapshots") or []
    n = now if now is not None else time.time()
    cutoff = n - days * 86400.0
    filtered: list[dict[str, Any]] = []
    for s in snapshots:
        ts = float(s.get("ts", 0) or 0)
        if ts < cutoff:
            continue
        if store_id and str(s.get("store_id")) != store_id:
            continue
        filtered.append(s)
    filtered.sort(
        key=lambda s: float(s.get("ts", 0) or 0),
        reverse=True,
    )
    return filtered


def compute_trend(
    *,
    store_id: str,
    days: int = 30,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute first-half vs second-half avg gross_profit.
    Returns {first_avg, second_avg, delta, slope_pct, verdict,
    sample_count}."""
    snaps = query(
        store_id=store_id, days=days, now=now,
    )
    # Sort oldest first for trend calc
    snaps_sorted = sorted(
        snaps, key=lambda s: float(s.get("ts", 0) or 0),
    )
    n = len(snaps_sorted)
    out = {
        "store_id": store_id,
        "sample_count": n,
        "first_avg": 0.0,
        "second_avg": 0.0,
        "delta": 0.0,
        "slope_pct": 0.0,
        "verdict": "no_data",
    }
    if n < 4:
        return out
    half = n // 2
    first = snaps_sorted[:half]
    second = snaps_sorted[half:]
    def _avg(rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        total = sum(
            float(r.get("gross_profit") or 0.0)
            for r in rows
        )
        return total / len(rows)
    fa = _avg(first)
    sa = _avg(second)
    out["first_avg"] = round(fa, 2)
    out["second_avg"] = round(sa, 2)
    out["delta"] = round(sa - fa, 2)
    if abs(fa) > 0.5:
        out["slope_pct"] = round(
            (sa - fa) / abs(fa) * 100.0, 1,
        )
    if abs(out["delta"]) < 1.0:
        out["verdict"] = "flat"
    elif out["delta"] > 0:
        out["verdict"] = "rising"
    else:
        out["verdict"] = "falling"
    return out


def snapshot_count() -> int:
    return len(_load_raw().get("snapshots") or [])


def stores_with_history() -> list[str]:
    raw = _load_raw()
    seen: list[str] = []
    for s in raw.get("snapshots") or []:
        sid = str(s.get("store_id") or "")
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def reset_path(path: Path) -> None:
    """Test-only hook to override the persistence path."""
    global _PATH
    _PATH = path
