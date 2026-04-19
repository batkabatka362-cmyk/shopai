"""Error pattern library — learn from failures, suggest remedies.

When a Shopify call fails with ``429 Too Many Requests`` we know to
back off. When ``401 Unauthorized`` happens we refresh the token.
These are *patterns* — but they often live scattered in try/except
branches with no cross-learning. If a new subsystem hits ``429`` it
starts from zero.

This library keeps a shared registry. An error is captured as:

  • signature — canonical "error class" (e.g. "shopify:429")
  • context_fingerprint — dict of free-form canonical fields
    (endpoint, verb, payload_keys)
  • attempted_remedies — what we tried, did it fix the issue

Given a new error, ``suggest(signature, context)`` returns the
remedy with the highest historical success rate. Unknown errors
return ``None`` so callers can fall back to default handling *and*
``observe(..., remedy=..., worked=...)`` teaches the library.

Pure stdlib, SQLite-persisted, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.error_pattern_library")


_DROP_KEYS = ("ts", "timestamp", "id", "uuid", "request_id")


@dataclass
class ErrorObservation:
    signature: str
    context_fingerprint: dict[str, Any]
    remedy: str
    worked: bool
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "context_fingerprint": dict(self.context_fingerprint),
            "remedy": self.remedy,
            "worked": self.worked,
            "ts": self.ts,
        }


@dataclass
class RemedySuggestion:
    signature: str
    remedy: str
    success_rate: float
    n_attempts: int
    n_successes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "remedy": self.remedy,
            "success_rate": round(self.success_rate, 4),
            "n_attempts": self.n_attempts,
            "n_successes": self.n_successes,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_observations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    signature          TEXT NOT NULL,
    context_json       TEXT NOT NULL,
    remedy             TEXT NOT NULL,
    worked             INTEGER NOT NULL,
    ts                 REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_err_sig
    ON error_observations(signature);
"""


def _canonical_context(
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not context:
        return {}
    out: dict[str, Any] = {}
    for k, v in context.items():
        if k in _DROP_KEYS:
            continue
        out[k] = v
    return dict(sorted(out.items()))


class ErrorPatternLibrary:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._observations: list[ErrorObservation] = []
        # signature → remedy → [attempts, successes]
        self._remedy_stats: dict[str, dict[str, list[int]]] = (
            defaultdict(lambda: defaultdict(lambda: [0, 0]))
        )
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
                "SELECT signature, context_json, remedy, "
                "worked, ts FROM error_observations",
            ):
                try:
                    ctx = json.loads(row[1] or "{}")
                except (json.JSONDecodeError, ValueError):
                    continue
                obs = ErrorObservation(
                    signature=row[0],
                    context_fingerprint=ctx,
                    remedy=row[2],
                    worked=bool(row[3]),
                    ts=float(row[4]),
                )
                self._observations.append(obs)
                stats = self._remedy_stats[obs.signature][obs.remedy]
                stats[0] += 1
                if obs.worked:
                    stats[1] += 1

    # ── Intake ───────────────────────────────────────────

    def observe(
        self,
        *,
        signature: str,
        context: dict[str, Any] | None = None,
        remedy: str,
        worked: bool,
        ts: float | None = None,
    ) -> ErrorObservation:
        if not signature:
            raise ValueError("signature required")
        if not remedy:
            raise ValueError("remedy required")
        timestamp = float(ts if ts is not None else time.time())
        ctx = _canonical_context(context)
        obs = ErrorObservation(
            signature=str(signature),
            context_fingerprint=ctx,
            remedy=str(remedy),
            worked=bool(worked),
            ts=timestamp,
        )
        with self._lock:
            self._observations.append(obs)
            stats = self._remedy_stats[obs.signature][obs.remedy]
            stats[0] += 1
            if obs.worked:
                stats[1] += 1
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO error_observations"
                    "(signature, context_json, remedy, worked, ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        obs.signature,
                        json.dumps(ctx, sort_keys=True),
                        obs.remedy,
                        1 if obs.worked else 0,
                        obs.ts,
                    ),
                )
                self._conn.commit()
        return obs

    # ── Suggest ──────────────────────────────────────────

    def suggest(
        self,
        signature: str,
        *,
        context: dict[str, Any] | None = None,
        min_attempts: int = 1,
    ) -> RemedySuggestion | None:
        if not signature:
            raise ValueError("signature required")
        with self._lock:
            remedies = dict(self._remedy_stats.get(signature, {}))
        if not remedies:
            return None
        best: RemedySuggestion | None = None
        for remedy, (attempts, successes) in remedies.items():
            if attempts < min_attempts:
                continue
            rate = successes / attempts if attempts else 0.0
            candidate = RemedySuggestion(
                signature=signature,
                remedy=remedy,
                success_rate=rate,
                n_attempts=attempts,
                n_successes=successes,
            )
            if best is None or candidate.success_rate > best.success_rate:
                best = candidate
            elif candidate.success_rate == best.success_rate and (
                candidate.n_attempts > best.n_attempts
            ):
                best = candidate
        return best

    def suggestions(
        self,
        signature: str,
    ) -> list[RemedySuggestion]:
        with self._lock:
            remedies = dict(self._remedy_stats.get(signature, {}))
        out: list[RemedySuggestion] = []
        for remedy, (attempts, successes) in remedies.items():
            rate = successes / attempts if attempts else 0.0
            out.append(RemedySuggestion(
                signature=signature,
                remedy=remedy,
                success_rate=rate,
                n_attempts=attempts,
                n_successes=successes,
            ))
        out.sort(
            key=lambda s: (-s.success_rate, -s.n_attempts),
        )
        return out

    # ── Queries ──────────────────────────────────────────

    def known_signatures(self) -> list[str]:
        with self._lock:
            return sorted(self._remedy_stats.keys())

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_obs = len(self._observations)
            n_sigs = len(self._remedy_stats)
            overall_success = (
                sum(1 for o in self._observations if o.worked)
                / total_obs if total_obs else 0.0
            )
        return {
            "observations": total_obs,
            "signatures": n_sigs,
            "overall_success_rate": round(overall_success, 4),
        }

    def reset(self) -> int:
        with self._lock:
            n = len(self._observations)
            self._observations.clear()
            self._remedy_stats.clear()
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM error_observations",
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
