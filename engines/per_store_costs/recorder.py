"""Append-only event recorder for per-store adapter costs.

Design priorities (in order):

  1. Low per-call overhead. record_call() opens the log
     in append mode, writes one JSON line, closes.
     No full-file read. No JSON-array reparse.
     Typical: <1ms per call. Adapter throughput preserved.

  2. Crash-safe. JSONL is line-atomic at the filesystem
     layer (POSIX O_APPEND + Windows opened with append
     flag). A crash mid-write loses AT MOST the in-flight
     line; the rest of the log stays parseable.

  3. Bounded size. Auto-rotates when active file exceeds
     5MB (~50k events). Rotation moves the live file to
     ``<name>.archive.jsonl`` (overwriting any prior
     archive); queries can opt into reading the archive.

  4. Pattern J guard. Short-circuits under pytest so
     unit tests don't pollute the production cost log.
     Tests that NEED to exercise the recorder install an
     autouse fixture patching ``_is_test_environment``
     to False.

  5. Backward compat. record_call() is best-effort:
     ANY exception in recording is logged at DEBUG and
     swallowed. Adapter throughput is the priority;
     observability is the bonus.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Public for tests; can be patched.
DATA_PATH = Path("data/per_store_costs.jsonl")
ARCHIVE_PATH = Path("data/per_store_costs.archive.jsonl")

# Rotation threshold. 5MB is roughly 50k events at the
# current per-line size; comfortably 1-2 weeks of
# production traffic for a 20-store empire.
_ROTATE_AT_BYTES = 5 * 1024 * 1024

# Re-entrant lock so concurrent adapter calls from
# multiple threads serialise their writes without
# deadlocking each other.
_WRITE_LOCK = threading.RLock()


@dataclass
class CostEvent:
    """One adapter-call attribution event."""
    ts: float
    store_id: str
    adapter: str
    capability: str
    cost_usd: float
    latency_ms: float
    ok: bool


def _is_test_environment() -> bool:
    """Pattern J guard. Short-circuit under pytest unless
    SHOPAI_FORCE_PRODUCTION_WRITES=1.

    Tests can also patch this function to ``return False``
    to exercise the recorder during a targeted unit test.
    """
    if os.environ.get(
        "SHOPAI_FORCE_PRODUCTION_WRITES", "",
    ).lower() in ("1", "true", "yes"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _active_store_id() -> str:
    """Read the thread-local active_store. Returns empty
    string when no store is active (fleet-level call)."""
    try:
        from core.context import get_active_store_id
        return get_active_store_id() or ""
    except Exception:  # noqa: BLE001
        return ""


def rotate_if_needed() -> bool:
    """Rotate the live log to archive when it exceeds
    _ROTATE_AT_BYTES.

    Returns True if rotation happened. Caller-safe:
    holds the lock so concurrent record_call invocations
    do not race the rotation.
    """
    try:
        with _WRITE_LOCK:
            if not DATA_PATH.exists():
                return False
            size = DATA_PATH.stat().st_size
            if size < _ROTATE_AT_BYTES:
                return False
            # Atomic replace: new archive overwrites prior
            # archive in one step. Subsequent record_calls
            # create a fresh empty live file.
            DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            os.replace(DATA_PATH, ARCHIVE_PATH)
            logger.info(
                "per_store_costs: rotated %d bytes "
                "to archive", size,
            )
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_costs rotate raised: %s", exc,
        )
        return False


def record_call(
    *,
    adapter: str,
    capability: str,
    cost_usd: float = 0.0,
    latency_ms: float = 0.0,
    ok: bool = True,
    store_id: str | None = None,
) -> bool:
    """Append one adapter-call event. Best-effort.

    Returns True if the event was written, False if
    skipped (test guard, write failure, or invalid input).
    """
    if _is_test_environment():
        return False
    if not adapter or not capability:
        return False

    # Resolve store_id: explicit > active_store thread-local
    sid = (
        store_id
        if store_id is not None
        else _active_store_id()
    )

    event = CostEvent(
        ts=time.time(),
        store_id=sid,
        adapter=str(adapter),
        capability=str(capability),
        cost_usd=float(cost_usd or 0.0),
        latency_ms=float(latency_ms or 0.0),
        ok=bool(ok),
    )

    try:
        line = json.dumps(asdict(event), default=str) + "\n"
    except (TypeError, ValueError) as exc:
        logger.debug(
            "per_store_costs: serialise raised: %s", exc,
        )
        return False

    try:
        with _WRITE_LOCK:
            DATA_PATH.parent.mkdir(
                parents=True, exist_ok=True,
            )
            with open(
                DATA_PATH, "a", encoding="utf-8",
            ) as f:
                f.write(line)
                # Flush so concurrent readers see the
                # event immediately (a stat() based query
                # would miss in-buffer data otherwise).
                f.flush()

        # Best-effort rotation check (lock-acquired inside
        # rotate_if_needed). Failure is non-fatal.
        rotate_if_needed()
        return True
    except OSError as exc:
        logger.debug(
            "per_store_costs: write raised: %s", exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "per_store_costs: unexpected: %s", exc,
        )
        return False


def entry_count() -> int:
    """Test/diagnostic helper. Cheap line count of the
    live log. Returns 0 when the file does not exist."""
    if not DATA_PATH.exists():
        return 0
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def clear_log_for_tests() -> None:
    """Wipe both live + archive. Used by tests after
    Pattern J guard is patched off so the test starts from
    a clean slate."""
    for p in (DATA_PATH, ARCHIVE_PATH):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
