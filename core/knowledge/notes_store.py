"""Persistent operator-notes store.

JSON-backed key-value store for operator commentary on engines and
goals. The importer (``importer.py``) writes notes here; engine
flows / digest reads can read them back. Persistence is a single
JSON file at ``data/operator_notes.json`` — simple, inspectable,
no schema migrations.

Storage shape
-------------
::

    {
      "engines": {
        "<engine_name>": {
          "notes": "<markdown body>",
          "updated_at": <epoch>,
          "source_path": "<original vault path>"
        },
        ...
      },
      "goals": {
        "<goal_name>": {...same shape},
        ...
      },
      "meta": {
        "last_import_at": <epoch>,
        "last_import_source": "<vault path>",
        "imported_count": <int>
      }
    }

Atomic writes via temp file + rename so a partial crash can't
corrupt the file. Returns empty dicts if the file is missing /
unparseable — the operator should be able to delete and start
fresh.

Concurrency
-----------
A single process-wide ``threading.Lock`` guards every read/write.
The store is small enough that lock contention is irrelevant
in practice — most workloads do one import then several reads.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("core.knowledge.notes_store")


_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "operator_notes.json"
)


class NotesStore:
    """Persistent operator-notes key-value store.

    Args:
        path: Override the default JSON file location. Tests pass
            a ``tmp_path / "notes.json"`` for isolation.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    # ── Read API ──────────────────────────────────────────────

    def get_engine_notes(self, engine: str) -> str:
        """Return notes for ``engine``, or empty string if absent."""
        entry = self._load().get("engines", {}).get(engine)
        if not isinstance(entry, dict):
            return ""
        return str(entry.get("notes", "") or "")

    def get_goal_notes(self, goal: str) -> str:
        entry = self._load().get("goals", {}).get(goal)
        if not isinstance(entry, dict):
            return ""
        return str(entry.get("notes", "") or "")

    def all_engine_notes(self) -> dict[str, dict[str, Any]]:
        """Full ``{engine: entry}`` mapping. Empty when no notes."""
        data = self._load()
        engines = data.get("engines") or {}
        return {
            k: dict(v) for k, v in engines.items()
            if isinstance(v, dict)
        }

    def all_goal_notes(self) -> dict[str, dict[str, Any]]:
        data = self._load()
        goals = data.get("goals") or {}
        return {
            k: dict(v) for k, v in goals.items() if isinstance(v, dict)
        }

    def meta(self) -> dict[str, Any]:
        return dict(self._load().get("meta") or {})

    # ── Write API ─────────────────────────────────────────────

    def set_engine_notes(
        self,
        engine: str,
        notes: str,
        *,
        source_path: str = "",
    ) -> None:
        self._set_one("engines", engine, notes, source_path)

    def set_goal_notes(
        self,
        goal: str,
        notes: str,
        *,
        source_path: str = "",
    ) -> None:
        self._set_one("goals", goal, notes, source_path)

    def replace_all(
        self,
        engine_notes: dict[str, str],
        goal_notes: dict[str, str],
        *,
        source_path: str = "",
        engine_sources: dict[str, str] | None = None,
        goal_sources: dict[str, str] | None = None,
    ) -> None:
        """Atomic full replacement.

        Used by the importer after a fresh vault walk so old
        entries that no longer exist in the vault don't linger.
        Optional ``engine_sources`` / ``goal_sources`` map provide
        per-entry source paths; missing entries fall back to the
        outer ``source_path``.
        """
        engine_sources = engine_sources or {}
        goal_sources = goal_sources or {}
        now = time.time()
        new_data: dict[str, Any] = {
            "engines": {
                name: {
                    "notes": str(text),
                    "updated_at": now,
                    "source_path": engine_sources.get(name, source_path),
                }
                for name, text in engine_notes.items()
                if isinstance(name, str) and isinstance(text, str)
            },
            "goals": {
                name: {
                    "notes": str(text),
                    "updated_at": now,
                    "source_path": goal_sources.get(name, source_path),
                }
                for name, text in goal_notes.items()
                if isinstance(name, str) and isinstance(text, str)
            },
            "meta": {
                "last_import_at": now,
                "last_import_source": source_path,
                "imported_count": (
                    len(engine_notes) + len(goal_notes)
                ),
            },
        }
        with self._lock:
            self._atomic_write(new_data)

    def clear(self) -> None:
        """Drop every entry. Mostly for tests."""
        with self._lock:
            self._atomic_write({
                "engines": {},
                "goals": {},
                "meta": {},
            })

    # ── Internal ──────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        with self._lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> dict[str, Any]:
        """Load WITHOUT acquiring self._lock. Callers that
        already hold the lock (e.g., to span load+mutate+write)
        invoke this; everyone else uses _load."""
        if not self._path.exists():
            return {"engines": {}, "goals": {}, "meta": {}}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "notes file read failed: %s", exc,
            )
            return {"engines": {}, "goals": {}, "meta": {}}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.debug(
                "notes file corrupted (json parse): %s", exc,
            )
            return {"engines": {}, "goals": {}, "meta": {}}
        # Defensive — ensure top-level shape
        if not isinstance(data, dict):
            return {"engines": {}, "goals": {}, "meta": {}}
        data.setdefault("engines", {})
        data.setdefault("goals", {})
        data.setdefault("meta", {})
        return data

    def _set_one(
        self,
        bucket: str,
        name: str,
        notes: str,
        source_path: str,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        if not isinstance(notes, str):
            return
        # W962-74: load + mutate + atomic_write under a single
        # lock acquisition. Pre-fix had _load acquire-release
        # outside the lock, then re-enter for the write — two
        # concurrent _set_one calls could both load the same
        # snapshot and the second one's atomic_write would wipe
        # the first one's added entry (classic lost update).
        with self._lock:
            data = self._load_unlocked()
            section = data.setdefault(bucket, {})
            section[name.strip()] = {
                "notes": notes,
                "updated_at": time.time(),
                "source_path": source_path,
            }
            self._atomic_write(data)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        """Write via temp + os.replace so a crash mid-write can't
        leave a half-flushed JSON file behind."""
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        finally:
            try:
                tmp.unlink(missing_ok=True)  # W962-68 TOCTOU
            except OSError as exc:
                logger.debug(
                "tmp file cleanup failed: %s", exc,
                )


# Module-level singleton used by importer + future readers.
# Tests construct their own NotesStore(path=tmp_path / ...) for
# isolation.
_DEFAULT_STORE: NotesStore | None = None


def get_default_store() -> NotesStore:
    """Lazy singleton for the default-location store."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = NotesStore()
    return _DEFAULT_STORE
