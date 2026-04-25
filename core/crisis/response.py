"""Crisis responder — 5-minute response window for live incidents.

Sprint 3 S3-10 (P3, LX.4 in docs/AGI_STACK.md). Pairs with L7
risk_tripwire (hard $-caps) and L8 launch_simulator (pre-flight
projection). Those two prevent *predicted* bad outcomes; this
module reacts to *observed* bad outcomes before they compound.

Event kinds the brain can register (caller-driven — no magic
subscription):

  * ``chargeback_spike``   — multiple chargebacks in a short window
  * ``platform_ban``       — Meta / Google / TikTok account disabled
  * ``shopify_risk_review``— store under manual review
  * ``fraud_velocity``     — order velocity anomaly
  * ``auth_failure_burst`` — repeated 401s across adapters
  * ``owner_halt``         — owner pressed the big red button

State transitions:

    green  — no active triggers
    yellow — 1 trigger in the last ``window_s`` OR an env-level
             ``SHOPAI_CRISIS_WARN=1``
    red    — 2+ triggers in the last ``window_s`` OR a single
             ``severity=critical`` trigger OR the kill switch
             ``SHOPAI_EMERGENCY_HALT=1``

Write paths should call ``is_halted()`` and short-circuit when the
responder returns True. ``halt()`` / ``resume()`` provide manual
override — persisted to SQLite so a restart doesn't silently
re-arm.

Pure stdlib. Thread-safe (Lock). LLM-free. Deterministic under a
fixed ``now_fn``.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ENV_HALT = "SHOPAI_EMERGENCY_HALT"
_ENV_WARN = "SHOPAI_CRISIS_WARN"
_DEFAULT_WINDOW_S = 30 * 60.0      # 30 minutes
_DEFAULT_RED_THRESHOLD = 2

_SEVERITY_TIERS = ("info", "warning", "critical")

_KNOWN_KINDS = (
    "chargeback_spike",
    "platform_ban",
    "shopify_risk_review",
    "fraud_velocity",
    "auth_failure_burst",
    "owner_halt",
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS crisis_events (
    id         TEXT PRIMARY KEY,
    ts         REAL NOT NULL,
    kind       TEXT NOT NULL,
    severity   TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    meta       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_crisis_ts
    ON crisis_events(ts);

CREATE TABLE IF NOT EXISTS crisis_flags (
    name       TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


@dataclass
class CrisisEvent:
    id: str
    ts: float
    kind: str
    severity: str
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind,
            "severity": self.severity,
            "note": self.note,
            "meta": dict(self.meta),
        }


@dataclass
class CrisisState:
    level: str                  # "green" | "yellow" | "red"
    triggered_kinds: tuple[str, ...] = ()
    recent_event_count: int = 0
    halted: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "triggered_kinds": list(
                self.triggered_kinds,
            ),
            "recent_event_count": self.recent_event_count,
            "halted": self.halted,
            "reason": self.reason,
        }


class CrisisResponder:
    """Event-driven crisis state + kill switch."""

    def __init__(
        self,
        db_path: str | Path = "data/crisis.db",
        *,
        window_s: float = _DEFAULT_WINDOW_S,
        red_threshold: int = _DEFAULT_RED_THRESHOLD,
        now_fn: Any = None,
    ) -> None:
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        if red_threshold < 1:
            raise ValueError(
                "red_threshold must be ≥ 1",
            )
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.Lock()
        self._window_s = float(window_s)
        self._red_threshold = int(red_threshold)
        self._now_fn = now_fn or time.time
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Events ───────────────────────────────────────────

    def register_event(
        self,
        *,
        kind: str,
        severity: str = "warning",
        note: str = "",
        meta: dict[str, Any] | None = None,
    ) -> CrisisEvent:
        if not kind:
            raise ValueError("kind required")
        severity = severity or "warning"
        if severity not in _SEVERITY_TIERS:
            raise ValueError(
                f"severity must be one of "
                f"{_SEVERITY_TIERS}, got {severity!r}",
            )
        now = float(self._now_fn())
        eid = uuid.uuid4().hex
        meta_json = json.dumps(meta or {}, sort_keys=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO crisis_events"
                "(id, ts, kind, severity, note, meta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    eid, now, str(kind), severity,
                    str(note), meta_json,
                ),
            )
            self._conn.commit()
        return CrisisEvent(
            id=eid, ts=now,
            kind=str(kind),
            severity=severity,
            note=str(note),
            meta=dict(meta or {}),
        )

    def recent_events(
        self, *, limit: int = 50,
    ) -> list[CrisisEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, kind, severity, note, meta "
                "FROM crisis_events ORDER BY ts DESC "
                "LIMIT ?",
                (int(limit),),
            ).fetchall()
        out: list[CrisisEvent] = []
        for r in rows:
            try:
                meta = json.loads(r[5] or "{}")
            except (TypeError, ValueError):
                meta = {}
            out.append(CrisisEvent(
                id=r[0], ts=float(r[1]),
                kind=r[2], severity=r[3],
                note=r[4], meta=meta,
            ))
        return out

    # ── State ────────────────────────────────────────────

    def _active_events(
        self, *, now: float,
    ) -> list[CrisisEvent]:
        cutoff = now - self._window_s
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, kind, severity, note, meta "
                "FROM crisis_events "
                "WHERE ts >= ? ORDER BY ts DESC",
                (cutoff,),
            ).fetchall()
        out: list[CrisisEvent] = []
        for r in rows:
            try:
                meta = json.loads(r[5] or "{}")
            except (TypeError, ValueError):
                meta = {}
            out.append(CrisisEvent(
                id=r[0], ts=float(r[1]),
                kind=r[2], severity=r[3],
                note=r[4], meta=meta,
            ))
        return out

    def detect_state(self) -> CrisisState:
        now = float(self._now_fn())
        env_halt = os.environ.get(_ENV_HALT, "") == "1"
        env_warn = os.environ.get(_ENV_WARN, "") == "1"
        manual_halt = self._flag_bool("manual_halt")
        events = self._active_events(now=now)
        kinds: tuple[str, ...] = tuple(
            sorted({e.kind for e in events}),
        )
        has_critical = any(
            e.severity == "critical" for e in events
        )

        halted = env_halt or manual_halt
        if halted:
            reason = (
                "kill switch: "
                + (
                    f"env {_ENV_HALT}=1"
                    if env_halt
                    else "manual halt()"
                )
            )
            return CrisisState(
                level="red",
                triggered_kinds=kinds,
                recent_event_count=len(events),
                halted=True,
                reason=reason,
            )
        if has_critical:
            return CrisisState(
                level="red",
                triggered_kinds=kinds,
                recent_event_count=len(events),
                halted=True,
                reason=(
                    "critical event in last "
                    f"{int(self._window_s/60)}min"
                ),
            )
        if len(events) >= self._red_threshold:
            return CrisisState(
                level="red",
                triggered_kinds=kinds,
                recent_event_count=len(events),
                halted=True,
                reason=(
                    f"{len(events)} events ≥ threshold "
                    f"{self._red_threshold}"
                ),
            )
        if events or env_warn:
            return CrisisState(
                level="yellow",
                triggered_kinds=kinds,
                recent_event_count=len(events),
                halted=False,
                reason=(
                    f"{len(events)} active events"
                    if events
                    else f"env {_ENV_WARN}=1"
                ),
            )
        return CrisisState(
            level="green",
            triggered_kinds=(),
            recent_event_count=0,
            halted=False,
            reason="no active events",
        )

    def is_halted(self) -> bool:
        return self.detect_state().halted

    # ── Manual override ──────────────────────────────────

    def halt(self, *, reason: str = "") -> None:
        self._set_flag("manual_halt", "1")
        if reason:
            self.register_event(
                kind="owner_halt",
                severity="critical",
                note=reason,
            )

    def resume(self) -> None:
        self._set_flag("manual_halt", "")

    # ── Flag helpers ─────────────────────────────────────

    def _flag_bool(self, name: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM crisis_flags "
                "WHERE name=?",
                (name,),
            ).fetchone()
        return bool(row and row[0] == "1")

    def _set_flag(self, name: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO crisis_flags"
                "(name, value, updated_at) VALUES"
                "(?, ?, ?)",
                (name, value, float(self._now_fn())),
            )
            self._conn.commit()

    # ── Diagnostics ──────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        state = self.detect_state()
        with self._lock:
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM crisis_events",
            ).fetchone()[0])
        return {
            "state": state.as_dict(),
            "total_events": total,
            "window_s": self._window_s,
            "red_threshold": self._red_threshold,
            "env_halt_set": (
                os.environ.get(_ENV_HALT, "") == "1"
            ),
            "env_warn_set": (
                os.environ.get(_ENV_WARN, "") == "1"
            ),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Facade singleton ─────────────────────────────────────────

_SINGLETON: CrisisResponder | None = None
_SINGLETON_LOCK = threading.Lock()


def get_crisis_responder() -> CrisisResponder:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = CrisisResponder()
    return _SINGLETON


def reset_crisis_responder_for_tests() -> None:
    """Clears the module-level singleton (test-only helper)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                # Log and swallow — close is best-effort in
                # test teardown, and callers expect the reset
                # to always succeed.
                from utils.logger import get_logger
                get_logger("core.crisis").debug(
                    "reset_crisis close skipped: %s", exc,
                )
        _SINGLETON = None
