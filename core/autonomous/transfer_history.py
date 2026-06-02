"""Persistent log of cycle-driven auto-transfers.

When the TRANSFER phase of ``shopai autonomous-cycle``
enqueues a cross-store learning suggestion, this module
records the event so operators can audit:

  - "How many transfers did the cycle propose this week?"
  - "Which source stores have been seeding the most?"
  - "Did any transfer end up succeeding on the target?"

Pattern matches ``cycle_history`` / ``alert_history`` /
``auto_demote_history``: JSON file, atomic temp+rename,
fail-open reads, 1000-event cap, Pattern J guard.

Public surface
--------------
- ``TransferEvent`` dataclass.
- ``record_transfer(target_store_id, source_store_id,
  engine, action_type, capability, action_id, metrics)``.
- ``recent_history(since_seconds)``.
- ``transfer_stats(since_seconds)`` -- per-source / per-
  target / total rollup.
- ``clear()`` -- operator escape hatch.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# W962-43: spanning lock for concurrent record_transfer calls.
_LOCK = threading.RLock()


_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_TRANSFER_HISTORY_PATH",
        "data/transfer_history.json",
    )
)

_MAX_EVENTS = 1000


@dataclass
class TransferEvent:
    """One auto-transfer enqueue."""

    target_store_id: str
    source_store_id: str
    engine: str
    action_type: str
    capability: str
    recorded_at: float
    action_id: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_raw() -> list[dict[str, Any]]:
    try:
        if not _HISTORY_PATH.exists():
            return []
        with _HISTORY_PATH.open(
            "r", encoding="utf-8",
        ) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [
                e for e in data if isinstance(e, dict)
            ]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "transfer_history: load failed (%s)", exc,
        )
        return []


def _atomic_write(entries: list[dict[str, Any]]) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "transfer_history: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".transfer_hist_",
            suffix=".json",
            dir=str(_HISTORY_PATH.parent),
        )
        try:
            with os.fdopen(
                fd, "w", encoding="utf-8",
            ) as f:
                json.dump(
                    entries, f, indent=2, default=str,
                )
            os.replace(temp_path_str, _HISTORY_PATH)
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError as cleanup_exc:
                logger.debug(
                    "temp cleanup failed: %s", cleanup_exc,
                )
            raise
    except OSError as exc:
        logger.debug(
            "transfer_history: write failed (%s)", exc,
        )


def record_transfer(
    *,
    target_store_id: str,
    source_store_id: str,
    engine: str,
    action_type: str,
    capability: str,
    action_id: str | None = None,
    metrics: dict[str, Any] | None = None,
) -> bool:
    """Append a transfer event. Returns True on write,
    False on test-env / I/O error / invalid args."""
    if not all([
        target_store_id, source_store_id,
        engine, action_type,
    ]):
        return False
    if _is_test_environment():
        return False
    event = TransferEvent(
        target_store_id=target_store_id,
        source_store_id=source_store_id,
        engine=engine,
        action_type=action_type,
        capability=capability,
        recorded_at=time.time(),
        action_id=action_id,
        metrics=dict(metrics or {}),
    )
    # W962-43: span load+append+write.
    with _LOCK:
        entries = _load_raw()
        entries.append(asdict(event))
        if len(entries) > _MAX_EVENTS:
            entries = entries[-_MAX_EVENTS:]
        _atomic_write(entries)
    return True


def recent_history(
    *,
    since_seconds: int = 86400 * 7,
    target_store_id: str | None = None,
    now: float | None = None,
) -> list[TransferEvent]:
    """Newest-first events in the window. Optional
    target_store_id filter for per-store views."""
    now = now if now is not None else time.time()
    cutoff = now - since_seconds
    raw = _load_raw()
    events: list[TransferEvent] = []
    for r in raw:
        ts = float(r.get("recorded_at", 0) or 0)
        if ts < cutoff:
            continue
        if target_store_id is not None and (
            r.get("target_store_id") != target_store_id
        ):
            continue
        events.append(TransferEvent(
            target_store_id=str(
                r.get("target_store_id", "") or "",
            ),
            source_store_id=str(
                r.get("source_store_id", "") or "",
            ),
            engine=str(r.get("engine", "") or ""),
            action_type=str(r.get("action_type", "") or ""),
            capability=str(r.get("capability", "") or ""),
            recorded_at=ts,
            action_id=r.get("action_id"),
            metrics=dict(r.get("metrics", {}) or {}),
        ))
    events.reverse()
    events.sort(key=lambda e: -e.recorded_at)
    return events


def transfer_stats(
    *,
    since_seconds: int = 86400 * 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Rollup stats. Returns:
      {
        "total": int,
        "by_target": {store_id: count},
        "by_source": {store_id: count},
        "by_engine": {engine: count},
        "last_transfer_at": float | None,
      }
    """
    events = recent_history(
        since_seconds=since_seconds, now=now,
    )
    out: dict[str, Any] = {
        "total": len(events),
        "by_target": {},
        "by_source": {},
        "by_engine": {},
        "last_transfer_at": None,
    }
    if not events:
        return out
    out["last_transfer_at"] = events[0].recorded_at
    for e in events:
        out["by_target"][e.target_store_id] = (
            out["by_target"].get(e.target_store_id, 0) + 1
        )
        out["by_source"][e.source_store_id] = (
            out["by_source"].get(e.source_store_id, 0) + 1
        )
        out["by_engine"][e.engine] = (
            out["by_engine"].get(e.engine, 0) + 1
        )
    return out


def clear() -> None:
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "transfer_history: unlink raised: %s",
                exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
