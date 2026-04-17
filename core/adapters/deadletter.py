"""Dead-letter ledger — Option Y.

When every candidate in the router's fallback chain fails *and* the
retry policy runs out of attempts, the final failure is returned to
the caller and — historically — that was the end of it. The caller
logged it, the dashboard showed a success-rate dip, and nobody ever
went back to the actual call that broke.

The dead-letter ledger captures those exhausted calls to a local
JSONL file so operators can:

  * see what broke (adapter, capability, params hash, error message,
    attempts, timestamp) without needing to replay logs
  * replay specific calls after a fix — same params, same capability,
    through a fresh router pass so the now-healthy adapter picks it up
  * prune or archive the ledger when it grows past a soft cap

Design rules:

* **Append-only on-disk.** The ledger is a JSONL file written with a
  ``RLock`` around every line. A single line-flush ``write() +
  flush()`` is atomic enough for a single-node operator dashboard;
  we do NOT try to cover multi-writer contention because the router
  is the only writer in the process.
* **Never raise from ``record``.** If disk is full or the parent dir
  disappeared, the ledger logs the failure and continues. The
  router must never refuse to return a failure result just because
  the ledger died.
* **Bounded memory mirror.** The last N entries are kept in memory
  for O(1) dashboard reads. Tail reads beyond that fall back to a
  file scan.
* **Params are hashed, not copied.** The ledger records a params
  hash + the capability so a replay call can reconstruct the request
  from the caller side, but does not persist potentially PII-bearing
  params bodies into an unencrypted file on disk.

The router hook lives in ``router.execute`` inside the "all fallbacks
failed" branch — a single ``get_dead_letter_ledger().record(...)``
call right before returning the terminal failure.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Entry ──────────────────────────────────────────────────────


@dataclass
class DeadLetterEntry:
    """One exhausted-call record.

    The timestamps are wall-clock seconds since epoch (not monotonic)
    so operators can correlate with vendor-side dashboards.
    """

    id: str
    adapter: str
    capability: str
    params_hash: str
    params_snapshot: dict[str, Any]
    error_type: str
    error_message: str
    attempts: int
    timestamp: float
    tags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "adapter": self.adapter,
            "capability": self.capability,
            "params_hash": self.params_hash,
            "params_snapshot": dict(self.params_snapshot),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "attempts": self.attempts,
            "timestamp": self.timestamp,
            "tags": dict(self.tags),
        }

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=repr)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "DeadLetterEntry":
        return cls(
            id=str(row.get("id", "")),
            adapter=str(row.get("adapter", "")),
            capability=str(row.get("capability", "")),
            params_hash=str(row.get("params_hash", "")),
            params_snapshot=dict(row.get("params_snapshot") or {}),
            error_type=str(row.get("error_type", "")),
            error_message=str(row.get("error_message", "")),
            attempts=int(row.get("attempts", 0)),
            timestamp=float(row.get("timestamp", 0.0)),
            tags=dict(row.get("tags") or {}),
        )


# ── Ledger ────────────────────────────────────────────────────


class DeadLetterLedger:
    """In-memory + on-disk log of exhausted router calls.

    ``path`` is optional — pass ``None`` for a purely in-memory
    ledger (test mode). ``max_memory`` controls the in-memory
    mirror size; the disk file grows indefinitely unless the
    operator calls :meth:`prune` or rotates externally.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        max_memory: int = 200,
        clock=time.time,
    ) -> None:
        if max_memory < 1:
            raise ValueError("max_memory must be >= 1")
        self._path = Path(path) if path else None
        self._max_memory = max_memory
        self._clock = clock
        self._memory: deque[DeadLetterEntry] = deque(maxlen=max_memory)
        self._lock = threading.RLock()
        self._counter = 0
        self._total_records = 0
        self._total_write_failures = 0
        self._load_tail()

    # ── persistence ──────────────────────────────────────

    def _load_tail(self) -> None:
        """On startup, rehydrate the in-memory mirror from the tail
        of the file so the dashboard's first render doesn't show an
        empty panel just because the process just rebooted.

        Silently succeeds on a missing or malformed file — the
        ledger is a best-effort record, never a source of truth.
        """
        if self._path is None or not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                # Cheap approach: read all lines, keep the last N.
                lines = f.readlines()
        except OSError as exc:
            logger.debug("deadletter: tail load failed: %s", exc)
            return
        tail = lines[-self._max_memory:]
        with self._lock:
            for raw in tail:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                entry = DeadLetterEntry.from_dict(row)
                self._memory.append(entry)

    def _append_line(self, line: str) -> bool:
        """Write one JSONL line. Returns True on success."""
        if self._path is None:
            return True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
            return True
        except OSError as exc:
            logger.warning("deadletter: append failed: %s", exc)
            self._total_write_failures += 1
            return False

    # ── record / read ────────────────────────────────────

    def record(
        self,
        *,
        adapter: str,
        capability: str,
        params_hash: str,
        error_type: str,
        error_message: str,
        attempts: int,
        params_snapshot: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
    ) -> DeadLetterEntry:
        """Persist one exhausted-call record.

        ``params_snapshot`` is an optional small dict of non-PII
        fields the caller wants preserved verbatim (e.g. model name,
        prompt length). The full params body is intentionally not
        stored — the hash is the replay key.
        """
        with self._lock:
            self._counter += 1
            self._total_records += 1
            entry = DeadLetterEntry(
                id=f"dl-{int(self._clock() * 1000)}-{self._counter}",
                adapter=str(adapter),
                capability=str(capability),
                params_hash=str(params_hash),
                params_snapshot=dict(params_snapshot or {}),
                error_type=str(error_type),
                error_message=str(error_message)[:500],
                attempts=int(attempts),
                timestamp=float(self._clock()),
                tags=dict(tags or {}),
            )
            self._memory.append(entry)
        self._append_line(entry.to_json_line())
        return entry

    def recent(self, limit: int = 50) -> list[DeadLetterEntry]:
        """Return the most recent ``limit`` entries (newest first)."""
        if limit < 0:
            raise ValueError("limit must be >= 0")
        with self._lock:
            items = list(self._memory)
        items.reverse()
        return items[:limit]

    def filter(
        self,
        *,
        adapter: str | None = None,
        capability: str | None = None,
        since_ts: float | None = None,
        limit: int = 200,
    ) -> list[DeadLetterEntry]:
        """Return the subset of the in-memory mirror matching every
        non-None filter, most recent first. Beyond the in-memory
        horizon the ledger's on-disk file must be scanned externally.
        """
        if limit < 0:
            raise ValueError("limit must be >= 0")
        with self._lock:
            items = list(self._memory)
        items.reverse()
        out: list[DeadLetterEntry] = []
        for e in items:
            if adapter is not None and e.adapter != adapter:
                continue
            if capability is not None and e.capability != capability:
                continue
            if since_ts is not None and e.timestamp < since_ts:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    def size(self) -> int:
        with self._lock:
            return len(self._memory)

    # ── housekeeping ─────────────────────────────────────

    def prune(
        self,
        *,
        before_ts: float | None = None,
        adapter: str | None = None,
    ) -> int:
        """Drop in-memory entries matching the filter.

        Pruning does NOT rewrite the on-disk file — operators can
        rotate it externally. The return value is the number of
        in-memory entries removed.
        """
        with self._lock:
            kept: deque[DeadLetterEntry] = deque(maxlen=self._max_memory)
            dropped = 0
            for e in self._memory:
                drop = True
                if before_ts is not None and e.timestamp >= before_ts:
                    drop = False
                if adapter is not None and e.adapter != adapter:
                    drop = False
                # Need ALL supplied criteria to match before dropping.
                if before_ts is None and adapter is None:
                    drop = True
                if drop:
                    dropped += 1
                else:
                    kept.append(e)
            self._memory = kept
            return dropped

    def clear(self) -> int:
        """Test helper — drop everything in memory, return count."""
        with self._lock:
            n = len(self._memory)
            self._memory.clear()
            return n

    # ── snapshot / rollup ────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe summary for the dashboard rollup endpoint."""
        with self._lock:
            per_adapter: dict[str, int] = {}
            per_capability: dict[str, int] = {}
            recent_iter = list(self._memory)
            newest_ts = 0.0
            oldest_ts = 0.0
            for e in recent_iter:
                per_adapter[e.adapter] = per_adapter.get(e.adapter, 0) + 1
                per_capability[e.capability] = per_capability.get(e.capability, 0) + 1
                if e.timestamp > newest_ts:
                    newest_ts = e.timestamp
                if oldest_ts == 0.0 or e.timestamp < oldest_ts:
                    oldest_ts = e.timestamp
            return {
                "size": len(recent_iter),
                "total_records": self._total_records,
                "write_failures": self._total_write_failures,
                "per_adapter": per_adapter,
                "per_capability": per_capability,
                "newest_ts": newest_ts,
                "oldest_ts": oldest_ts,
                "path": str(self._path) if self._path else None,
            }


# ── Singleton ────────────────────────────────────────────────


_DEFAULT_PATH_ENV = "SHOPAI_DEADLETTER_PATH"
_DEFAULT_PATH = "core/adapters/.state/deadletter.jsonl"

_default_ledger: DeadLetterLedger | None = None
_default_lock = threading.Lock()


def get_dead_letter_ledger() -> DeadLetterLedger:
    """Return the process-wide ledger singleton.

    The on-disk path defaults to ``core/adapters/.state/deadletter.jsonl``
    under the repo root, overridable with ``SHOPAI_DEADLETTER_PATH``.
    Tests that don't want real disk I/O should either call
    ``reset_dead_letter_ledger`` between runs or pass
    ``DeadLetterLedger(path=None)`` as an explicit dependency.
    """
    global _default_ledger
    if _default_ledger is None:
        with _default_lock:
            if _default_ledger is None:
                path = os.environ.get(_DEFAULT_PATH_ENV, _DEFAULT_PATH)
                _default_ledger = DeadLetterLedger(path=path)
    return _default_ledger


def reset_dead_letter_ledger() -> None:
    """Drop the singleton — next ``get`` rebuilds from the env path."""
    global _default_ledger
    with _default_lock:
        _default_ledger = None


# ── Convenience: filter helpers ───────────────────────────────


def recent_entries(limit: int = 50) -> list[DeadLetterEntry]:
    """Shortcut for dashboard code that just wants the last N."""
    return get_dead_letter_ledger().recent(limit=limit)


def entries_for_adapter(
    adapter: str, *, limit: int = 50,
) -> list[DeadLetterEntry]:
    return get_dead_letter_ledger().filter(adapter=adapter, limit=limit)


def iter_file_entries(
    path: str | os.PathLike[str],
) -> Iterable[DeadLetterEntry]:
    """Yield every entry stored in the on-disk file — use for admin
    tooling that wants to page past the in-memory horizon.

    Malformed lines are silently skipped (the file is a best-effort
    record, not a source of truth).
    """
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            yield DeadLetterEntry.from_dict(row)
