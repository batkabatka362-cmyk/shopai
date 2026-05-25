"""Persist + retrieve cycle run history.

After each `shopai cycle run --yes` invocation, the result
should be recorded so operators can answer:
  - "When did the last cycle run?"
  - "Did the cycle fire correctly this morning?"
  - "Per-store: how many engines successfully fired?"
  - "What's the trend in error rate?"

JSON-on-disk persistence (data/cycle_history.json) keyed
by run_id (timestamp-based). Bounded to last 200 entries.

## API

  record_cycle_run(run_summary) -> CycleRun
  recent_runs(limit=20) -> list[CycleRun]
  last_run() -> CycleRun | None
  runs_for_store(store_id, limit=20) -> list[CycleRun]
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CycleRun:
    run_id: str
    started_at: float
    cycle_label: str
    mode: str  # "dry_run" or "live"
    total_stores: int = 0
    total_invoked: int = 0
    total_ok: int = 0
    total_errors: int = 0
    per_store: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "cycle_label": self.cycle_label,
            "mode": self.mode,
            "total_stores": self.total_stores,
            "total_invoked": self.total_invoked,
            "total_ok": self.total_ok,
            "total_errors": self.total_errors,
            "per_store": self.per_store,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CycleRun":
        return cls(
            run_id=str(d.get("run_id", "")),
            started_at=float(d.get("started_at", 0.0) or 0.0),
            cycle_label=str(d.get("cycle_label", "")),
            mode=str(d.get("mode", "dry_run")),
            total_stores=int(d.get("total_stores", 0) or 0),
            total_invoked=int(d.get("total_invoked", 0) or 0),
            total_ok=int(d.get("total_ok", 0) or 0),
            total_errors=int(d.get("total_errors", 0) or 0),
            per_store=d.get("per_store") or [],
        )

    @property
    def success_rate(self) -> float:
        if self.total_invoked == 0:
            return 0.0
        return round(self.total_ok / self.total_invoked, 3)

    @property
    def verdict(self) -> str:
        if self.mode == "dry_run":
            return "dry_run"
        if self.total_invoked == 0:
            return "empty"
        if self.total_errors == 0:
            return "clean"
        if self.success_rate >= 0.8:
            return "mostly_ok"
        if self.success_rate >= 0.5:
            return "degraded"
        return "failed"


def _history_path() -> Path:
    """Distinct filename to avoid colliding with the older
    core.autonomous.cycle_history (which writes
    data/cycle_history.json for the legacy autonomous-cycle
    command). Empire cycle history lives in a separate file."""
    data_dir = Path(
        os.environ.get("SHOPAI_DATA_DIR", "data")
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "empire_cycle_history.json"


def _load() -> list[CycleRun]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [
            CycleRun.from_dict(d) for d in raw
            if isinstance(d, dict)
        ]
    except (json.JSONDecodeError, OSError):
        return []


def _save(runs: list[CycleRun]) -> bool:
    path = _history_path()
    try:
        path.write_text(
            json.dumps(
                [r.to_dict() for r in runs],
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _short_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def record_cycle_run(
    *,
    cycle_label: str,
    mode: str,
    total_stores: int,
    total_invoked: int = 0,
    total_ok: int = 0,
    total_errors: int = 0,
    per_store: list[dict[str, Any]] | None = None,
) -> CycleRun:
    """Persist one cycle run's summary."""
    # ns-precision started_at: time.time() at second granularity
    # on Windows can produce identical timestamps for back-to-
    # back record calls; ns-precision dodges that tie.
    now_ns = time.time_ns()
    run = CycleRun(
        run_id=f"cycle_{now_ns // 1_000_000}_{_short_id()}",
        started_at=now_ns / 1e9,
        cycle_label=cycle_label,
        mode=mode,
        total_stores=total_stores,
        total_invoked=total_invoked,
        total_ok=total_ok,
        total_errors=total_errors,
        per_store=list(per_store or []),
    )
    runs = _load()
    runs.append(run)
    # Bound history to most-recent 200
    if len(runs) > 200:
        runs = runs[-200:]
    _save(runs)
    return run


def recent_runs(*, limit: int = 20) -> list[CycleRun]:
    """Most recent N runs, newest-first."""
    runs = _load()
    # Tie-break on run_id (which carries ms-precision timestamp +
    # short_id suffix). Without this, two records with identical
    # started_at -- common on Windows clock granularity -- sort
    # in load order, breaking last_run() determinism.
    runs.sort(
        key=lambda r: (r.started_at, r.run_id), reverse=True,
    )
    return runs[:limit]


def last_run() -> CycleRun | None:
    """The single most-recent cycle run, None if no history."""
    runs = recent_runs(limit=1)
    return runs[0] if runs else None


def runs_for_store(
    store_id: str, *, limit: int = 20,
) -> list[CycleRun]:
    """Filter recent runs to those that touched a given store."""
    out: list[CycleRun] = []
    for run in recent_runs(limit=100):
        if any(
            s.get("store_id") == store_id for s in run.per_store
        ):
            out.append(run)
        if len(out) >= limit:
            break
    return out


def clear_history() -> bool:
    """Wipe history -- tests / operator reset."""
    return _save([])
