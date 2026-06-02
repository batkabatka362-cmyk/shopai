"""Global Brain — memory store.

Persistent JSON-based memory store for structured knowledge records.
Each record is stored as a separate JSON file keyed by entry_id.

No connections to other modules — called only from memory_writer/memory_reader.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from typing import Any


_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")

# W962-74: process-local lock guarding the read+update+write
# race in MemoryStore.read on the access_count counter.
# Pre-fix two concurrent reads of the same entry could both
# load access_count=N, both compute N+1, both save N+1 -- a
# silent undercount that distorts which records the recommender
# treats as "frequently accessed".
_MEMORY_LOCK = threading.RLock()


class MemoryStore:
    """JSON-file-based persistent memory store for knowledge records."""

    def __init__(self) -> None:
        self._ensure_dir()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def write(self, entry_id: str, knowledge: dict[str, Any],
              score: float = 0.0) -> dict[str, Any]:
        """Write a knowledge record to memory.

        Args:
            entry_id: Unique identifier for the entry.
            knowledge: StructuredKnowledge dict to store.
            score: Composite score from the scorer.

        Returns:
            Confirmation dict with status.
        """
        try:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            record: dict[str, Any] = {
                "entry_id": entry_id,
                "knowledge": copy.deepcopy(knowledge),
                "score": round(score, 4),
                "stored_at": timestamp,
                "access_count": 0,
                "last_accessed": timestamp,
            }

            fpath = os.path.join(_MEMORY_DIR, f"{entry_id}.json")
            with open(fpath, "w", encoding="utf-8") as fh:
                json.dump(record, fh, indent=2, default=str)

            return {"status": "success", "entry_id": entry_id, "path": fpath}

        except Exception as exc:
            return {
                "status": "warning",
                "entry_id": entry_id,
                "note": f"Memory write failed (non-fatal): {exc}",
            }

    def read(self, entry_id: str) -> dict[str, Any] | None:
        """Read a single record by ID and update access metadata.

        W962-74: load + mutate + write happens under
        ``_MEMORY_LOCK`` and via atomic temp+rename so:
        - Two concurrent reads of the same entry cannot both
          undercount access_count.
        - A crash mid-write cannot leave a partial / empty JSON
          file that the except clause silently swallows.
        """
        fpath = os.path.join(_MEMORY_DIR, f"{entry_id}.json")
        if not os.path.isfile(fpath):
            return None
        try:
            with _MEMORY_LOCK:
                with open(fpath, "r", encoding="utf-8") as fh:
                    record = json.load(fh)
                if not isinstance(record, dict):
                    return None

                # Update access metadata
                record["access_count"] = record.get("access_count", 0) + 1
                record["last_accessed"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                )

                # Atomic write via temp + rename so a crash
                # mid-write doesn't leave a half-flushed JSON
                # file that the except clause below would
                # silently surface as None.
                fd, tmp_path = tempfile.mkstemp(
                    prefix=f".{entry_id}_",
                    suffix=".json.tmp",
                    dir=_MEMORY_DIR,
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(record, fh, indent=2, default=str)
                    os.replace(tmp_path, fpath)
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise

                return copy.deepcopy(record)
        except (json.JSONDecodeError, OSError):
            return None

    def read_all(
        self,
        category: str = "",
        source_engine: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read all records with optional filtering.

        Args:
            category: Filter by knowledge category (empty = all).
            source_engine: Filter by source engine (empty = all).
            limit: Maximum records to return.

        Returns:
            List of MemoryEntry dicts sorted by score descending.
        """
        records = self._load_all()

        if category:
            records = [
                r for r in records
                if r.get("knowledge", {}).get("category", "") == category
            ]
        if source_engine:
            records = [
                r for r in records
                if r.get("knowledge", {}).get("source_engine", "") == source_engine
            ]

        records.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return copy.deepcopy(records[:limit])

    def count(self) -> int:
        """Return total number of records."""
        if not os.path.isdir(_MEMORY_DIR):
            return 0
        return sum(1 for f in os.listdir(_MEMORY_DIR) if f.endswith(".json"))

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Create memory directory if it doesn't exist."""
        os.makedirs(_MEMORY_DIR, exist_ok=True)

    def _load_all(self) -> list[dict[str, Any]]:
        """Load all records from disk."""
        if not os.path.isdir(_MEMORY_DIR):
            return []

        records: list[dict[str, Any]] = []
        for fname in os.listdir(_MEMORY_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(_MEMORY_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return records
