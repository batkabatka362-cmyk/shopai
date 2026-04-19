"""Meta-reasoner — reasoning about the brain's own reasoning.

Every decision ships with a claimed confidence (0..1). Over time we
can ask a second-order question: *is the brain's confidence itself
trustworthy?* If claimed_confidence=0.9 decisions fail 40% of the
time, the brain is overconfident and downstream code that uses
confidence as a gate is miscalibrated.

Meta-reasoner ingests ``record(decision_id, claimed_confidence,
outcome_positive)`` and computes:

  • calibration_error — average |claimed - actual| across buckets
  • overconfidence_score — tendency to claim > actual
  • reliability_per_bucket — observed success rate for each 0.1 band
  • adjusted_confidence(raw) — learned mapping that *would* be better

A second flavour of reasoning-about-reasoning is *which signals* the
brain keeps using that don't pay off. ``record_signal_use`` and
``signal_weight`` surface signals whose inclusion does not raise the
hit rate — candidates for pruning.

Pure stdlib, SQLite-persisted, deterministic. Complements
self_revision_journal (which edits rules) and attention_calibrator
(which scores what got attended).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.meta_reasoner")


_BUCKET_EDGES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01)


@dataclass
class BucketStat:
    low: float
    high: float
    n: int
    positives: int

    @property
    def hit_rate(self) -> float:
        return self.positives / self.n if self.n > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "low": round(self.low, 2),
            "high": round(self.high, 2),
            "n": self.n,
            "positives": self.positives,
            "hit_rate": round(self.hit_rate, 4),
        }


@dataclass
class CalibrationReport:
    buckets: list[BucketStat]
    calibration_error: float    # avg |claimed_mid - hit_rate|
    overconfidence_score: float # claimed_mid - hit_rate (mean)
    n_total: int
    signal_weights: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "buckets": [b.as_dict() for b in self.buckets],
            "calibration_error": round(self.calibration_error, 4),
            "overconfidence_score": round(
                self.overconfidence_score, 4,
            ),
            "n_total": self.n_total,
            "signal_weights": {
                k: round(v, 4) for k, v in self.signal_weights.items()
            },
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         TEXT NOT NULL,
    claimed_confidence  REAL NOT NULL,
    outcome_positive    INTEGER NOT NULL,
    ts                  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cal_ts ON calibration(ts);
CREATE TABLE IF NOT EXISTS signal_use (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         TEXT NOT NULL,
    signal              TEXT NOT NULL,
    outcome_positive    INTEGER NOT NULL,
    ts                  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sig_name ON signal_use(signal);
"""


def _bucket_for(value: float) -> tuple[float, float]:
    v = max(0.0, min(1.0, float(value)))
    for i in range(len(_BUCKET_EDGES) - 1):
        low = _BUCKET_EDGES[i]
        high = _BUCKET_EDGES[i + 1]
        if low <= v < high:
            return low, min(high, 1.0)
    return 0.9, 1.0


class MetaReasoner:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._calibration: list[tuple[str, float, bool, float]] = []
        # (decision_id, claimed_conf, outcome_pos, ts)
        self._signal_use: list[tuple[str, str, bool, float]] = []
        # (decision_id, signal, outcome_pos, ts)
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
                "SELECT decision_id, claimed_confidence, "
                "outcome_positive, ts FROM calibration",
            ):
                self._calibration.append((
                    row[0], float(row[1]),
                    bool(row[2]), float(row[3]),
                ))
            for row in self._conn.execute(
                "SELECT decision_id, signal, "
                "outcome_positive, ts FROM signal_use",
            ):
                self._signal_use.append((
                    row[0], row[1], bool(row[2]), float(row[3]),
                ))

    # ── Intake ───────────────────────────────────────────

    def record(
        self,
        *,
        decision_id: str,
        claimed_confidence: float,
        outcome_positive: bool,
        ts: float | None = None,
    ) -> None:
        if not decision_id:
            raise ValueError("decision_id required")
        if not 0.0 <= claimed_confidence <= 1.0:
            raise ValueError(
                "claimed_confidence must be in [0, 1]",
            )
        timestamp = float(ts if ts is not None else time.time())
        pos = bool(outcome_positive)
        with self._lock:
            self._calibration.append(
                (decision_id, float(claimed_confidence), pos, timestamp),
            )
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO calibration"
                    "(decision_id, claimed_confidence, "
                    " outcome_positive, ts) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        decision_id, float(claimed_confidence),
                        1 if pos else 0, timestamp,
                    ),
                )
                self._conn.commit()

    def record_signal_use(
        self,
        *,
        decision_id: str,
        signals: Iterable[str],
        outcome_positive: bool,
        ts: float | None = None,
    ) -> int:
        if not decision_id:
            raise ValueError("decision_id required")
        timestamp = float(ts if ts is not None else time.time())
        pos = bool(outcome_positive)
        n = 0
        with self._lock:
            for s in signals:
                if not s:
                    continue
                self._signal_use.append(
                    (decision_id, str(s), pos, timestamp),
                )
                if self._conn is not None:
                    self._conn.execute(
                        "INSERT INTO signal_use"
                        "(decision_id, signal, "
                        " outcome_positive, ts) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            decision_id, str(s),
                            1 if pos else 0, timestamp,
                        ),
                    )
                n += 1
            if self._conn is not None:
                self._conn.commit()
        return n

    # ── Analysis ─────────────────────────────────────────

    def _buckets(self) -> list[BucketStat]:
        stats: dict[tuple[float, float], list[int]] = {}
        with self._lock:
            records = list(self._calibration)
        for _, conf, pos, _ in records:
            key = _bucket_for(conf)
            bucket = stats.setdefault(key, [0, 0])
            bucket[0] += 1
            if pos:
                bucket[1] += 1
        out: list[BucketStat] = []
        for key in sorted(stats.keys()):
            low, high = key
            n, p = stats[key]
            out.append(BucketStat(low=low, high=high, n=n, positives=p))
        return out

    def calibrate(self) -> CalibrationReport:
        buckets = self._buckets()
        with self._lock:
            n_total = len(self._calibration)
        errors: list[float] = []
        overconfs: list[float] = []
        for b in buckets:
            mid = (b.low + b.high) / 2
            if mid > 1.0:
                mid = 1.0
            diff = mid - b.hit_rate
            errors.append(abs(diff))
            overconfs.append(diff)
        calibration_error = (
            sum(errors) / len(errors) if errors else 0.0
        )
        overconfidence_score = (
            sum(overconfs) / len(overconfs) if overconfs else 0.0
        )
        return CalibrationReport(
            buckets=buckets,
            calibration_error=calibration_error,
            overconfidence_score=overconfidence_score,
            n_total=n_total,
            signal_weights=self.signal_weights(),
        )

    def adjusted_confidence(self, claimed: float) -> float:
        """Return hit_rate of the bucket containing ``claimed``.

        If the bucket has no data, fall back to claimed.
        """
        if not 0.0 <= claimed <= 1.0:
            raise ValueError("claimed must be in [0, 1]")
        key = _bucket_for(claimed)
        stats = self._buckets()
        for b in stats:
            if (b.low, b.high) == key:
                if b.n >= 3:
                    return b.hit_rate
                break
        return float(claimed)

    def signal_weights(self) -> dict[str, float]:
        """For each signal, return hit_rate when it was *used*.

        Higher rate = more predictive. Callers compare to global hit
        rate to prune weak signals.
        """
        with self._lock:
            rows = list(self._signal_use)
        counts: dict[str, tuple[int, int]] = {}
        for _, signal, pos, _ in rows:
            n, p = counts.get(signal, (0, 0))
            n += 1
            p += 1 if pos else 0
            counts[signal] = (n, p)
        return {
            s: (p / n if n > 0 else 0.0)
            for s, (n, p) in counts.items()
        }

    def low_value_signals(
        self, *, floor: float = 0.5,
    ) -> list[str]:
        return sorted(
            s for s, w in self.signal_weights().items() if w < floor
        )

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "n_records": len(self._calibration),
                "n_signal_uses": len(self._signal_use),
                "distinct_signals": len(
                    {s for _, s, _, _ in self._signal_use},
                ),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._calibration) + len(self._signal_use)
            self._calibration.clear()
            self._signal_use.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM calibration")
                self._conn.execute("DELETE FROM signal_use")
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
