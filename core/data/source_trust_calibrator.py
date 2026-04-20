"""Source trust calibrator — per-source hit-rate × freshness.

Track 3 of AGI_HARDENING_PLAN. Sprint 3 shipped 5 winner sources
(CJ, AliExpress, peer store, manual seed, Meta ad library) — all
equally weighted when scoring a candidate. Reality is different:
one source might consistently produce winners while another
churns out duds. The calibrator tracks per-source hit-rate +
staleness and emits a trust score in [0, 1] that WinnerSearcher
uses to weight rankings.

Model (auditable):

    trust = win_ema × freshness_factor × (1 - error_rate_ema)

  * ``win_ema`` — EMA of outcome_ok across candidates from this
    source (α = 0.2). Bootstrap prior 0.5.
  * ``freshness_factor`` — exp(-staleness_s / decay_s); decays
    from 1.0 at fetch time to 0 as time elapses.
  * ``error_rate_ema`` — EMA of fetch failures vs attempts.

Owner can override a source's baseline via
``set_baseline_trust(source, trust)`` for soft tuning. Baselines
blend 50/50 with the calibrated trust until 20+ samples accrue.

Pure stdlib, SQLite-persisted, thread-safe (RLock). Deterministic
under fixed ``now_fn``.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.data.source_trust_calibrator")


_EMA_ALPHA = 0.2
_DEFAULT_DECAY_S = 7 * 24 * 3600.0   # 1 week
_DEFAULT_BASELINE_TRUST = 0.5
_WARMUP_SAMPLES = 20


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_name     TEXT PRIMARY KEY,
    win_ema         REAL NOT NULL DEFAULT 0.5,
    error_rate_ema  REAL NOT NULL DEFAULT 0.0,
    samples         INTEGER NOT NULL DEFAULT 0,
    fetch_attempts  INTEGER NOT NULL DEFAULT 0,
    fetch_errors    INTEGER NOT NULL DEFAULT 0,
    last_fetch_ts   REAL NOT NULL DEFAULT 0,
    baseline_trust  REAL NOT NULL DEFAULT 0.5,
    note            TEXT NOT NULL DEFAULT ''
);
"""


@dataclass
class SourceStats:
    source_name: str
    win_ema: float
    error_rate_ema: float
    samples: int
    fetch_attempts: int
    fetch_errors: int
    last_fetch_ts: float
    baseline_trust: float
    note: str = ""

    def freshness_factor(
        self, now: float, decay_s: float,
    ) -> float:
        if self.last_fetch_ts <= 0:
            return 0.0
        age = max(0.0, now - self.last_fetch_ts)
        return math.exp(-age / max(1.0, decay_s))

    def trust(
        self, *, now: float, decay_s: float,
        warmup: int = _WARMUP_SAMPLES,
    ) -> float:
        fresh = self.freshness_factor(
            now=now, decay_s=decay_s,
        )
        raw = (
            self.win_ema
            * fresh
            * max(0.0, 1.0 - self.error_rate_ema)
        )
        # Blend with baseline until warmup samples accrue
        if self.samples < warmup:
            w = self.samples / float(max(1, warmup))
            raw = raw * w + self.baseline_trust * (1.0 - w)
        return max(0.0, min(1.0, raw))

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "win_ema": round(self.win_ema, 4),
            "error_rate_ema": round(
                self.error_rate_ema, 4,
            ),
            "samples": self.samples,
            "fetch_attempts": self.fetch_attempts,
            "fetch_errors": self.fetch_errors,
            "last_fetch_ts": self.last_fetch_ts,
            "baseline_trust": round(
                self.baseline_trust, 4,
            ),
            "note": self.note,
        }


class SourceTrustCalibrator:
    """Per-source hit-rate EMA + freshness trust score."""

    def __init__(
        self,
        db_path: str | Path = (
            "data/source_trust.db"
        ),
        *,
        decay_s: float = _DEFAULT_DECAY_S,
        now_fn: Any = None,
    ) -> None:
        if decay_s <= 0:
            raise ValueError("decay_s must be > 0")
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.RLock()
        self._decay = float(decay_s)
        self._now_fn = now_fn or time.time
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Registration ─────────────────────────────────────

    def register(
        self,
        source_name: str,
        *,
        baseline_trust: float = _DEFAULT_BASELINE_TRUST,
        note: str = "",
    ) -> None:
        """Owner-facing registration. Re-calling updates
        baseline_trust + note. Internal callers use _ensure
        which is idempotent without touching baseline."""
        if not source_name:
            raise ValueError("source_name required")
        if not 0.0 <= baseline_trust <= 1.0:
            raise ValueError(
                "baseline_trust must be in [0, 1]",
            )
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO sources("
                "source_name, baseline_trust, note) "
                "VALUES(?, ?, ?)",
                (source_name, baseline_trust, note),
            )
            self._conn.execute(
                "UPDATE sources SET baseline_trust=?, "
                "note=? WHERE source_name=?",
                (baseline_trust, note, source_name),
            )
            self._conn.commit()

    def _ensure(self, source_name: str) -> None:
        """Idempotent "row exists" helper — never touches
        baseline_trust or note (those are owner-set)."""
        if not source_name:
            raise ValueError("source_name required")
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO sources("
                "source_name) VALUES(?)",
                (source_name,),
            )
            self._conn.commit()

    def set_baseline_trust(
        self, source_name: str, trust: float,
    ) -> None:
        if not 0.0 <= trust <= 1.0:
            raise ValueError(
                "trust must be in [0, 1]",
            )
        with self._lock:
            self._conn.execute(
                "UPDATE sources SET baseline_trust=? "
                "WHERE source_name=?",
                (trust, source_name),
            )
            self._conn.commit()

    # ── Record observations ─────────────────────────────

    def record_fetch(
        self, source_name: str, *, ok: bool,
    ) -> None:
        """A fetch attempt completed (ok=False for error)."""
        now = float(self._now_fn())
        self._ensure(source_name)
        with self._lock:
            stats = self._load(source_name)
            attempts = stats.fetch_attempts + 1
            errors = stats.fetch_errors + (0 if ok else 1)
            err_rate = errors / attempts
            last_fetch = now if ok else stats.last_fetch_ts
            self._conn.execute(
                "UPDATE sources SET "
                "fetch_attempts=?, fetch_errors=?, "
                "error_rate_ema=?, last_fetch_ts=? "
                "WHERE source_name=?",
                (
                    attempts, errors, err_rate,
                    last_fetch, source_name,
                ),
            )
            self._conn.commit()

    def record_outcome(
        self, source_name: str, *, won: bool,
    ) -> None:
        """A candidate from this source produced a real
        outcome. Updates win_ema."""
        self._ensure(source_name)
        with self._lock:
            stats = self._load(source_name)
            samples = stats.samples + 1
            new_ema = (
                _EMA_ALPHA * (1.0 if won else 0.0)
                + (1.0 - _EMA_ALPHA) * stats.win_ema
            )
            self._conn.execute(
                "UPDATE sources SET win_ema=?, "
                "samples=? WHERE source_name=?",
                (new_ema, samples, source_name),
            )
            self._conn.commit()

    # ── Query ────────────────────────────────────────────

    def trust(self, source_name: str) -> float:
        stats = self.get(source_name)
        if stats is None:
            return _DEFAULT_BASELINE_TRUST
        return stats.trust(
            now=float(self._now_fn()),
            decay_s=self._decay,
        )

    def get(
        self, source_name: str,
    ) -> SourceStats | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT source_name FROM sources "
                "WHERE source_name=?",
                (source_name,),
            ).fetchone()
        if row is None:
            return None
        return self._load(source_name)

    def ranked(self) -> list[tuple[str, float]]:
        """Every known source sorted by trust descending."""
        now = float(self._now_fn())
        with self._lock:
            rows = self._conn.execute(
                "SELECT source_name FROM sources",
            ).fetchall()
        out: list[tuple[str, float]] = []
        for r in rows:
            stats = self._load(r[0])
            out.append((
                r[0],
                stats.trust(
                    now=now, decay_s=self._decay,
                ),
            ))
        out.sort(key=lambda x: -x[1])
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(self._conn.execute(
                "SELECT COUNT(*) FROM sources",
            ).fetchone()[0])
        return {
            "total_sources": total,
            "decay_s": self._decay,
        }

    # ── Internal ─────────────────────────────────────────

    def _load(self, source_name: str) -> SourceStats:
        with self._lock:
            row = self._conn.execute(
                "SELECT source_name, win_ema, "
                "error_rate_ema, samples, fetch_attempts, "
                "fetch_errors, last_fetch_ts, "
                "baseline_trust, note FROM sources "
                "WHERE source_name=?",
                (source_name,),
            ).fetchone()
        if row is None:
            raise KeyError(source_name)
        return SourceStats(
            source_name=row[0],
            win_ema=float(row[1]),
            error_rate_ema=float(row[2]),
            samples=int(row[3]),
            fetch_attempts=int(row[4]),
            fetch_errors=int(row[5]),
            last_fetch_ts=float(row[6]),
            baseline_trust=float(row[7]),
            note=row[8],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: SourceTrustCalibrator | None = None
_SINGLETON_LOCK = threading.Lock()


def get_calibrator() -> SourceTrustCalibrator:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = SourceTrustCalibrator()
    return _SINGLETON


def reset_calibrator_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset calibrator close skipped: %s",
                    exc,
                )
        _SINGLETON = None
