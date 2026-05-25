"""Per-cycle attribution snapshots -- closes the trend loop.

Wave 7-10 captures revenue attribution at a moment in time.
Without persistence, every `shopai cycle attribution` is a
fresh snapshot -- operators can't answer "did last cycle
improve cluster X revenue?".

This module persists a compact attribution snapshot AT
cycle-run time so future queries can build trend lines:

  - "Revenue per cluster, last 10 cycles": done.
  - "Did Wave 10's revenue-aware captain shift revenue toward
    higher-earning engines?": done (compare before/after).
  - "Which cycle made the biggest revenue jump?": done.

## Storage

JSON-on-disk, ``data/attribution_snapshots.json``, bounded to
last 200 entries. Each snapshot carries:

  - snapshot_id (timestamp-based)
  - cycle_run_id (links back to CycleRun if recorded post-cycle)
  - captured_at
  - window_hours
  - store_id (None = fleet-wide)
  - attributed_revenue, total_orders_in_window,
    total_revenue_in_window, attribution_rate
  - per_cluster: [{cluster, attributed_revenue,
    attributed_orders, confidence}]
  - per_engine: [{engine, cluster, attributed_revenue,
    attributed_orders, confidence}]

We DON'T persist sample_orders or tag_matches -- that detail
belongs in live attribution queries, not the snapshot history.

## Pattern J guard

Same as cycle_history -- writes are skipped under PYTEST_CURRENT_TEST
so unit tests don't pollute the snapshot file.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AttributionSnapshot:
    snapshot_id: str
    captured_at: float
    window_hours: float
    store_id: str | None
    total_orders_in_window: int = 0
    total_revenue_in_window: float = 0.0
    attributed_revenue: float = 0.0
    attribution_rate: float = 0.0
    per_cluster: list[dict[str, Any]] = field(default_factory=list)
    per_engine: list[dict[str, Any]] = field(default_factory=list)
    cycle_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "captured_at": self.captured_at,
            "window_hours": self.window_hours,
            "store_id": self.store_id,
            "total_orders_in_window": self.total_orders_in_window,
            "total_revenue_in_window": self.total_revenue_in_window,
            "attributed_revenue": self.attributed_revenue,
            "attribution_rate": self.attribution_rate,
            "per_cluster": self.per_cluster,
            "per_engine": self.per_engine,
            "cycle_run_id": self.cycle_run_id,
        }


def _data_dir() -> Path:
    base = os.environ.get("SHOPAI_DATA_DIR")
    if base:
        p = Path(base)
    else:
        p = Path("data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path() -> Path:
    return _data_dir() / "attribution_snapshots.json"


def _load() -> list[AttributionSnapshot]:
    p = _path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[AttributionSnapshot] = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        try:
            out.append(AttributionSnapshot(
                snapshot_id=str(d.get("snapshot_id", "")),
                captured_at=float(d.get("captured_at", 0.0)),
                window_hours=float(d.get("window_hours", 0.0)),
                store_id=d.get("store_id"),
                total_orders_in_window=int(
                    d.get("total_orders_in_window", 0) or 0,
                ),
                total_revenue_in_window=float(
                    d.get("total_revenue_in_window", 0.0) or 0.0,
                ),
                attributed_revenue=float(
                    d.get("attributed_revenue", 0.0) or 0.0,
                ),
                attribution_rate=float(
                    d.get("attribution_rate", 0.0) or 0.0,
                ),
                per_cluster=list(d.get("per_cluster", []) or []),
                per_engine=list(d.get("per_engine", []) or []),
                cycle_run_id=d.get("cycle_run_id"),
            ))
        except (TypeError, ValueError):
            continue
    return out


def _save(snapshots: list[AttributionSnapshot]) -> None:
    p = _path()
    try:
        p.write_text(
            json.dumps(
                [s.to_dict() for s in snapshots],
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def record_snapshot(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
    cycle_run_id: str | None = None,
) -> AttributionSnapshot | None:
    """Capture + persist an attribution snapshot.

    Returns None under pytest (Pattern J guard) or when the
    attribution call fails.
    """
    if _is_test_environment():
        return None
    try:
        from engines._revenue_attribution import attribute_revenue
        report = attribute_revenue(
            window_hours=window_hours, store_id=store_id,
        )
    except Exception:  # noqa: BLE001
        return None

    now_ns = time.time_ns()
    snapshot = AttributionSnapshot(
        snapshot_id=f"attr_{now_ns // 1_000_000}",
        captured_at=now_ns / 1e9,
        window_hours=window_hours,
        store_id=store_id,
        total_orders_in_window=report.total_orders_in_window,
        total_revenue_in_window=round(
            report.total_revenue_in_window, 2,
        ),
        attributed_revenue=round(report.attributed_revenue, 2),
        attribution_rate=report.attribution_rate,
        per_cluster=[
            {
                "cluster": c.cluster,
                "attributed_revenue": round(
                    c.attributed_revenue, 2,
                ),
                "attributed_orders": c.attributed_orders,
                "confidence": c.confidence,
            }
            for c in report.per_cluster
        ],
        per_engine=[
            {
                "engine": e.engine,
                "cluster": e.cluster,
                "attributed_revenue": round(
                    e.attributed_revenue, 2,
                ),
                "attributed_orders": e.attributed_orders,
                "confidence": e.confidence,
            }
            for e in report.per_engine
        ],
        cycle_run_id=cycle_run_id,
    )
    snapshots = _load()
    snapshots.append(snapshot)
    if len(snapshots) > 200:
        snapshots = snapshots[-200:]
    _save(snapshots)
    return snapshot


def recent_snapshots(
    *, limit: int = 20, store_id: str | None = None,
) -> list[AttributionSnapshot]:
    """Most recent N snapshots, newest first. Optional per-store
    filter."""
    snapshots = _load()
    if store_id is not None:
        snapshots = [s for s in snapshots if s.store_id == store_id]
    snapshots.sort(
        key=lambda s: (s.captured_at, s.snapshot_id),
        reverse=True,
    )
    return snapshots[:limit]


def last_snapshot(
    *, store_id: str | None = None,
) -> AttributionSnapshot | None:
    """Most recent single snapshot, or None if no history."""
    snaps = recent_snapshots(limit=1, store_id=store_id)
    return snaps[0] if snaps else None


def attribution_trend(
    *,
    limit: int = 20,
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    """Compact trend view: one row per snapshot, oldest first.

    Useful for "is the autonomous loop improving revenue?".
    Each row: captured_at, attributed_revenue, total_orders,
    attribution_rate, top_cluster, top_engine.
    """
    snaps = recent_snapshots(limit=limit, store_id=store_id)
    snaps.reverse()  # oldest first for trend rendering
    out: list[dict[str, Any]] = []
    for s in snaps:
        top_cluster = (
            s.per_cluster[0]["cluster"] if s.per_cluster else None
        )
        top_engine = (
            s.per_engine[0]["engine"] if s.per_engine else None
        )
        out.append({
            "snapshot_id": s.snapshot_id,
            "captured_at": s.captured_at,
            "cycle_run_id": s.cycle_run_id,
            "window_hours": s.window_hours,
            "attributed_revenue": s.attributed_revenue,
            "total_orders_in_window": s.total_orders_in_window,
            "attribution_rate": s.attribution_rate,
            "top_cluster": top_cluster,
            "top_engine": top_engine,
        })
    return out


def clear_snapshots() -> None:
    """Test-helper: clear the snapshot file."""
    p = _path()
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass
