"""Capability registry — SQLite-persisted catalogue of brain skills.

The cognitive ``SelfModel`` narrates capabilities for owner-facing
prose and rolls up strengths/weaknesses from cycle telemetry. The
capability_registry sits underneath it as a simple persisted store:

  • every registered capability has (name, scope, proficiency,
    sample_count, last_exercised, gap_reason, note)
  • ``update(name, ok)`` folds a success/failure via EMA so the
    registry stays responsive to new evidence
  • ``can_do(name)`` returns a crisp boolean for the decision_stack
    to gate actions
  • ``gaps()``, ``known_edges()``, ``by_scope()`` answer the
    introspection queries

Complements ``core.cognitive.self_model`` by being strictly a
persisted registry — no narratives, no roll-ups — and durable across
restarts. Pure stdlib.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.capability_registry")


_DEFAULT_PROFICIENCY_FLOOR = 0.6


@dataclass
class Capability:
    name: str
    scope: str
    proficiency: float
    sample_count: int
    last_exercised: float
    gap_reason: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "proficiency": round(self.proficiency, 4),
            "sample_count": self.sample_count,
            "last_exercised": self.last_exercised,
            "gap_reason": self.gap_reason,
            "note": self.note,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS capabilities (
    name            TEXT PRIMARY KEY,
    scope           TEXT NOT NULL,
    proficiency     REAL NOT NULL,
    sample_count    INTEGER NOT NULL,
    last_exercised  REAL NOT NULL,
    gap_reason      TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cap_scope
    ON capabilities(scope);
"""


class CapabilityRegistry:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        proficiency_floor: float = _DEFAULT_PROFICIENCY_FLOOR,
    ) -> None:
        if not 0.0 < proficiency_floor <= 1.0:
            raise ValueError(
                "proficiency_floor must be in (0, 1]",
            )
        self._lock = threading.Lock()
        self._floor = float(proficiency_floor)
        self._caps: dict[str, Capability] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT name, scope, proficiency, sample_count, "
                "last_exercised, gap_reason, note "
                "FROM capabilities",
            ):
                self._caps[row[0]] = Capability(
                    name=row[0],
                    scope=row[1],
                    proficiency=float(row[2]),
                    sample_count=int(row[3]),
                    last_exercised=float(row[4]),
                    gap_reason=row[5] or "",
                    note=row[6] or "",
                )

    def _persist(self, cap: Capability) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO capabilities("
            "  name, scope, proficiency, sample_count, "
            "  last_exercised, gap_reason, note"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                cap.name, cap.scope, cap.proficiency,
                cap.sample_count, cap.last_exercised,
                cap.gap_reason, cap.note,
            ),
        )
        self._conn.commit()

    # ── Registry ─────────────────────────────────────────

    def register(
        self,
        *,
        name: str,
        scope: str,
        initial_proficiency: float = 0.5,
        gap_reason: str = "",
        note: str = "",
    ) -> Capability:
        if not name:
            raise ValueError("name required")
        if not scope:
            raise ValueError("scope required")
        if not 0.0 <= initial_proficiency <= 1.0:
            raise ValueError(
                "initial_proficiency must be in [0, 1]",
            )
        with self._lock:
            if name in self._caps:
                return self._caps[name]
            cap = Capability(
                name=str(name),
                scope=str(scope),
                proficiency=float(initial_proficiency),
                sample_count=0,
                last_exercised=0.0,
                gap_reason=str(gap_reason),
                note=str(note),
            )
            self._caps[cap.name] = cap
            self._persist(cap)
            return cap

    def declare_gap(
        self,
        *,
        name: str,
        scope: str,
        reason: str,
        note: str = "",
    ) -> Capability:
        if not reason:
            raise ValueError("reason required for gap")
        return self.register(
            name=name,
            scope=scope,
            initial_proficiency=0.0,
            gap_reason=reason,
            note=note,
        )

    # ── Update ───────────────────────────────────────────

    def update(
        self,
        name: str,
        *,
        ok: bool,
        ts: float | None = None,
    ) -> Capability:
        timestamp = float(ts if ts is not None else time.time())
        with self._lock:
            cap = self._caps.get(name)
            if cap is None:
                raise ValueError(
                    f"unknown capability {name!r}",
                )
            outcome = 1.0 if ok else 0.0
            if cap.sample_count == 0:
                cap.proficiency = outcome
            else:
                cap.proficiency = (
                    0.9 * cap.proficiency + 0.1 * outcome
                )
            cap.sample_count += 1
            cap.last_exercised = timestamp
            if cap.proficiency >= self._floor and cap.gap_reason:
                cap.gap_reason = ""
            self._persist(cap)
            return cap

    # ── Queries ──────────────────────────────────────────

    def can_do(self, name: str) -> bool:
        with self._lock:
            cap = self._caps.get(name)
        if cap is None:
            return False
        if cap.gap_reason:
            return False
        return cap.proficiency >= self._floor

    def capability(self, name: str) -> Capability | None:
        with self._lock:
            return self._caps.get(name)

    def gaps(self) -> list[Capability]:
        with self._lock:
            out = [
                c for c in self._caps.values()
                if c.gap_reason
                or c.proficiency < self._floor
            ]
        out.sort(key=lambda c: c.proficiency)
        return out

    def known_edges(self) -> list[str]:
        with self._lock:
            edges = sorted({
                c.scope for c in self._caps.values()
                if c.gap_reason
                or c.proficiency < self._floor
            })
        return edges

    def by_scope(self, scope: str) -> list[Capability]:
        with self._lock:
            return [
                c for c in self._caps.values()
                if c.scope == scope
            ]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._caps)
            ready = sum(
                1 for c in self._caps.values()
                if c.proficiency >= self._floor
                and not c.gap_reason
            )
            return {
                "total": total,
                "ready": ready,
                "gaps": total - ready,
                "proficiency_floor": self._floor,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._caps)
            self._caps.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM capabilities")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
