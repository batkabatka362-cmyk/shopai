"""World-model updater — detect reality drift, propose revisions.

world_model stores the brain's beliefs about how variables relate
("price ↑ by 10% → CVR ↓ by ~5%"). Over time the world changes:
price sensitivity drops in a trending category, competitors dump
inventory, or the creative shift changes CTR baselines. Without
feedback, the world_model's predictions grow stale and downstream
reasoning (forecaster, simulator, utility_blender) inherits the
error silently.

``WorldModelUpdater`` compares *predicted* KPI values against
*observed* values and maintains per-predictor drift metrics:

  • mse — mean squared error over a rolling window
  • bias — mean signed error (are we systematically over/under?)
  • drift_score — recent half vs older half t-like ratio

When drift_score exceeds ``drift_threshold`` and n ≥ ``min_samples``,
the module emits a ``DriftAlert`` with a suggested update
(e.g. ``new_intercept = old + bias``). Callers feed the alert into
``self_revision_journal`` so the proposal is auditable.

Pure stdlib, in-memory (SQLite-persist optional), deterministic.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Iterable

from utils.logger import get_logger


logger = get_logger("brain.world_model_updater")


_DEFAULT_DRIFT_THRESHOLD = 2.0


@dataclass
class PredictionRecord:
    predictor_id: str
    predicted: float
    observed: float
    ts: float

    @property
    def error(self) -> float:
        return self.observed - self.predicted

    def as_dict(self) -> dict[str, Any]:
        return {
            "predictor_id": self.predictor_id,
            "predicted": round(self.predicted, 4),
            "observed": round(self.observed, 4),
            "error": round(self.error, 4),
            "ts": self.ts,
        }


@dataclass
class DriftMetrics:
    predictor_id: str
    n_samples: int
    mse: float
    rmse: float
    bias: float
    drift_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "predictor_id": self.predictor_id,
            "n_samples": self.n_samples,
            "mse": round(self.mse, 6),
            "rmse": round(self.rmse, 6),
            "bias": round(self.bias, 6),
            "drift_score": round(self.drift_score, 4),
        }


@dataclass
class DriftAlert:
    id: str
    predictor_id: str
    drift_score: float
    bias: float
    n_samples: int
    suggestion: str
    suggested_adjustment: float   # how much to shift intercept
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "predictor_id": self.predictor_id,
            "drift_score": round(self.drift_score, 4),
            "bias": round(self.bias, 4),
            "n_samples": self.n_samples,
            "suggestion": self.suggestion,
            "suggested_adjustment": round(
                self.suggested_adjustment, 4,
            ),
            "ts": self.ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    predictor_id  TEXT NOT NULL,
    predicted     REAL NOT NULL,
    observed      REAL NOT NULL,
    ts            REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pr_pred_ts
    ON prediction_records(predictor_id, ts);
"""


def _mse(errs: list[float]) -> float:
    if not errs:
        return 0.0
    return sum(e * e for e in errs) / len(errs)


class WorldModelUpdater:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        window: int = 60,
        min_samples: int = 10,
        drift_threshold: float = _DEFAULT_DRIFT_THRESHOLD,
    ) -> None:
        if window < 6:
            raise ValueError("window must be ≥ 6")
        if min_samples < 4:
            raise ValueError("min_samples must be ≥ 4")
        if drift_threshold <= 0:
            raise ValueError("drift_threshold must be > 0")
        self._lock = threading.RLock()
        self._window = int(window)
        self._min_samples = int(min_samples)
        self._drift_threshold = float(drift_threshold)
        self._records: dict[str, Deque[PredictionRecord]] = (
            defaultdict(lambda: deque(maxlen=self._window))
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
                "SELECT predictor_id, predicted, observed, ts "
                "FROM prediction_records ORDER BY ts ASC",
            ):
                rec = PredictionRecord(
                    predictor_id=row[0],
                    predicted=float(row[1]),
                    observed=float(row[2]),
                    ts=float(row[3]),
                )
                self._records[rec.predictor_id].append(rec)

    # ── Intake ───────────────────────────────────────────

    def record(
        self,
        *,
        predictor_id: str,
        predicted: float,
        observed: float,
        ts: float | None = None,
    ) -> PredictionRecord:
        if not predictor_id:
            raise ValueError("predictor_id required")
        timestamp = float(ts if ts is not None else time.time())
        rec = PredictionRecord(
            predictor_id=str(predictor_id),
            predicted=float(predicted),
            observed=float(observed),
            ts=timestamp,
        )
        with self._lock:
            self._records[rec.predictor_id].append(rec)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT INTO prediction_records"
                    "(predictor_id, predicted, observed, ts) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        rec.predictor_id, rec.predicted,
                        rec.observed, rec.ts,
                    ),
                )
                self._conn.commit()
        return rec

    # ── Metrics ──────────────────────────────────────────

    def metrics(self, predictor_id: str) -> DriftMetrics | None:
        with self._lock:
            recs = list(self._records.get(predictor_id, ()))
        if not recs:
            return None
        errs = [r.error for r in recs]
        n = len(errs)
        mse = _mse(errs)
        rmse = math.sqrt(mse)
        bias = sum(errs) / n if n else 0.0
        if n < self._min_samples:
            drift = 0.0
        else:
            half = n // 2
            old_mse = _mse(errs[:half])
            new_mse = _mse(errs[half:])
            # drift_score: ratio (new+eps)/(old+eps)
            drift = (new_mse + 1e-9) / (old_mse + 1e-9)
        return DriftMetrics(
            predictor_id=predictor_id,
            n_samples=n,
            mse=mse,
            rmse=rmse,
            bias=bias,
            drift_score=drift,
        )

    # ── Alerting ─────────────────────────────────────────

    def detect_alerts(self) -> list[DriftAlert]:
        with self._lock:
            pids = list(self._records.keys())
        alerts: list[DriftAlert] = []
        for pid in pids:
            m = self.metrics(pid)
            if m is None:
                continue
            if m.n_samples < self._min_samples:
                continue
            if m.drift_score < self._drift_threshold:
                continue
            # Build a suggestion. If bias is non-trivial, propose an
            # intercept shift equal to the bias (observed − predicted).
            suggestion = (
                f"predictor {pid} drift={m.drift_score:.2f}x; "
                f"bias={m.bias:+.3f} → shift intercept by {m.bias:+.3f}"
            )
            alerts.append(DriftAlert(
                id=uuid.uuid4().hex,
                predictor_id=pid,
                drift_score=m.drift_score,
                bias=m.bias,
                n_samples=m.n_samples,
                suggestion=suggestion,
                suggested_adjustment=m.bias,
                ts=time.time(),
            ))
        return alerts

    # ── Queries ──────────────────────────────────────────

    def all_metrics(self) -> list[DriftMetrics]:
        with self._lock:
            pids = list(self._records.keys())
        out: list[DriftMetrics] = []
        for pid in pids:
            m = self.metrics(pid)
            if m is not None:
                out.append(m)
        out.sort(key=lambda m: -m.drift_score)
        return out

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_recs = sum(
                len(q) for q in self._records.values()
            )
            return {
                "tracked_predictors": len(self._records),
                "total_records": total_recs,
                "window": self._window,
                "min_samples": self._min_samples,
                "drift_threshold": self._drift_threshold,
            }

    def reset(self) -> int:
        with self._lock:
            n = sum(len(q) for q in self._records.values())
            self._records.clear()
            if self._conn is not None:
                self._conn.execute(
                    "DELETE FROM prediction_records",
                )
                self._conn.commit()
        return n

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
