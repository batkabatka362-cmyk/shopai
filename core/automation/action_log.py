"""Generic JSON-backed action log (Wave 117).

Extracts the pattern shared between
``engines/returns_management/refund_log.py`` (Wave 102) and
``engines/roas_guardrails/ad_spend_log.py`` (Wave 110): a
bounded JSON append log at a configurable path.

Future autonomous loops (fulfillment, customer outreach,
inventory restocking) get this for free without re-implementing
the boilerplate.

Each domain provides:
  - A LogEntry dataclass with the fields it cares about
  - A log path (e.g. ``data/inventory_log.json``)
  - The bounded max-entries limit (default 1000)

Pattern J guard: ``record_event`` no-ops under
``PYTEST_CURRENT_TEST``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ENTRIES = 1000

# W962-19 race fix: load + append + save in record_event used
# to happen unlocked; two writers (e.g. cycle-run thread +
# daily-brief) could clobber each other's appends. Per-path
# RLocks serialize the read-modify-write.
_PATH_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_MUTEX = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve()) if path.exists() else str(path)
    with _LOCKS_MUTEX:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def is_test_environment() -> bool:
    """Pattern J accessor. Re-exported so domain modules can
    consult it directly if they wrap record_event."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def load_log(path: Path) -> list[dict[str, Any]]:
    """Read + return the log entries as a list of dicts.
    Returns ``[]`` on any failure or missing file."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return raw
    except Exception as exc:  # noqa: BLE001
        logger.debug("action_log load raised: %s", exc)
    return []


def save_log(
    path: Path,
    entries: list[dict[str, Any]],
    *,
    max_entries: int = _DEFAULT_MAX_ENTRIES,
) -> None:
    """Save the entries to disk. Bounded by max_entries."""
    if is_test_environment():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(entries) > max_entries:
            entries = entries[-max_entries:]
        with path.open("w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
    except Exception as exc:  # noqa: BLE001
        logger.debug("action_log save raised: %s", exc)


def record_event(
    path: Path,
    event: Any,
    *,
    max_entries: int = _DEFAULT_MAX_ENTRIES,
) -> None:
    """Append a dataclass event to the log. No-op under pytest.

    ``event`` must be a dataclass instance; non-dataclass inputs
    are silently dropped (mirrors the Wave 102/110 pattern).
    """
    if is_test_environment():
        return
    if not is_dataclass(event):
        return
    # W962-19: hold the per-path lock across read+append+save
    # so concurrent producers don't lose updates.
    with _lock_for(path):
        rows = load_log(path)
        payload = asdict(event)
        if (
            "recorded_at" in payload
            and not payload["recorded_at"]
        ):
            payload["recorded_at"] = time.time()
        rows.append(payload)
        save_log(path, rows, max_entries=max_entries)


def recent_events(
    path: Path,
    *,
    window_hours: float = 168.0,
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Read the log + filter by window + optional equality
    filters (e.g. ``{"store_id": "a", "network": "meta"}``).

    Returns rows newest-first.
    """
    cutoff = time.time() - max(0.0, window_hours) * 3600.0
    rows = load_log(path)
    filters = filters or {}
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = r.get("recorded_at")
        if not isinstance(ts, (int, float)) or ts < cutoff:
            continue
        # Apply equality filters
        match = True
        for key, expected in filters.items():
            if not expected:
                continue
            if r.get(key) != expected:
                match = False
                break
        if match:
            out.append(r)
    out.sort(
        key=lambda row: row.get("recorded_at", 0),
        reverse=True,
    )
    return out


def log_size(path: Path) -> int:
    return len(load_log(path))
