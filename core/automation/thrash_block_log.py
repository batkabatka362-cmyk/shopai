"""Thrash guardrail block log (W930).

The Phase 6/7 wired appliers call ``record_writeback`` when
the thrash guardrail blocks a write. Those records flow into
MemoryIntelligence + DataArchitecture + LearningLoop, but
querying them later is heavy — the operator wants a fast
"what got blocked in the last hour?" answer.

This module is a parallel, bounded JSON log written
SPECIFICALLY for thrash-guardrail-blocked writebacks. It's a
read-side substrate; nothing depends on it for correctness.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


_DEFAULT_PATH = Path("data") / "thrash_block_log.json"
_MAX_ENTRIES = 500

# W962 race fix: record_block did _read + append + _write
# unlocked. Concurrent thrash-guardrail blocks (one per
# blocked engine per cycle, 10+ engines firing in parallel)
# could drop entries.
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


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@dataclass
class BlockEntry:
    blocked_at: float
    engine: str
    action_type: str
    capability: str
    store_id: str | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "blocked_at": self.blocked_at,
            "engine": self.engine,
            "action_type": self.action_type,
            "capability": self.capability,
            "store_id": self.store_id,
            "reason": self.reason,
        }


def _resolve(path: Path | None = None) -> Path:
    return path or _DEFAULT_PATH


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception as exc:  # noqa: BLE001
        logger.debug("thrash block log read raised: %s", exc)
    return []


def _write(path: Path, rows: list[dict]) -> None:
    """Atomic write via temp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bounded = rows[-_MAX_ENTRIES:]
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(bounded, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def record_block(
    *,
    engine: str,
    action_type: str,
    capability: str,
    store_id: str | None,
    reason: str,
    path: Path | None = None,
) -> None:
    """Append a blocked-writeback row (Pattern J guarded)."""
    if _is_test_environment():
        return
    p = _resolve(path)
    entry = BlockEntry(
        blocked_at=time.time(),
        engine=engine,
        action_type=action_type,
        capability=capability,
        store_id=store_id,
        reason=reason,
    )
    # W962: span the lock across read+append+write so two
    # concurrent blocked-writeback events don't clobber each
    # other.
    with _lock_for(p):
        rows = _read(p)
        rows.append(entry.to_dict())
        _write(p, rows)


def recent_blocks(
    *,
    limit: int = 50,
    window_hours: float | None = None,
    store_id: str | None = None,
    engine: str | None = None,
    path: Path | None = None,
) -> list[BlockEntry]:
    """Newest-first list of blocked writebacks."""
    p = _resolve(path)
    rows = _read(p)
    out: list[BlockEntry] = []
    cutoff = (
        time.time() - window_hours * 3600.0
        if window_hours else None
    )
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        # W937 bugfix: require at minimum engine + action_type
        # + blocked_at so malformed rows don't produce phantom
        # BlockEntry objects with empty strings + epoch 0.
        if not (
            row.get("engine")
            and row.get("action_type")
            and row.get("blocked_at")
        ):
            logger.debug(
                "skip block log row missing required fields: "
                "%s", row,
            )
            continue
        if store_id is not None:
            if row.get("store_id") != store_id:
                continue
        if engine is not None:
            if row.get("engine") != engine:
                continue
        if cutoff is not None:
            if float(row.get("blocked_at") or 0) < cutoff:
                continue
        try:
            out.append(BlockEntry(
                blocked_at=float(row.get("blocked_at", 0)),
                engine=str(row.get("engine", "")),
                action_type=str(row.get("action_type", "")),
                capability=str(row.get("capability", "")),
                store_id=row.get("store_id"),
                reason=str(row.get("reason", "")),
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "skip malformed block log row: %s", exc,
            )
            continue
        if len(out) >= limit:
            break
    return out


def block_count(*, path: Path | None = None) -> int:
    return len(_read(_resolve(path)))
