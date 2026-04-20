"""World model calibration — prediction vs realised + what-if.

Track 10 (final) of AGI_HARDENING_PLAN. core/brain/world_model
predicts KPI distributions; core/brain/world_model_updater
tracks prediction error for drift detection. This module wraps
both into a calibration layer that:

  * Tracks per-KPI calibration (EMA of |predicted - actual|)
  * Produces a *calibrated* prediction — base prediction
    widened by the observed error band so the quoted sigma
    reflects reality, not just the raw Welford variance.
  * Surfaces a ``what_if(action, context, kpi)`` entry point
    plus an ``explain(prediction)`` string for owner-facing
    CLI.

Pure stdlib. Deterministic under fixed now_fn. Lazy loads the
WorldModel so this module is testable without booting the real
DB.
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


logger = get_logger("core.brain.world_model_calibration")


_EMA_ALPHA = 0.2
_DEFAULT_WIDEN_FACTOR = 1.2


_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration (
    kpi            TEXT PRIMARY KEY,
    sample_count   INTEGER NOT NULL DEFAULT 0,
    error_abs_ema  REAL NOT NULL DEFAULT 0.0,
    bias_ema       REAL NOT NULL DEFAULT 0.0,
    last_update_ts REAL NOT NULL DEFAULT 0.0
);
"""


@dataclass
class CalibrationRecord:
    kpi: str
    sample_count: int
    error_abs_ema: float
    bias_ema: float
    last_update_ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "sample_count": self.sample_count,
            "error_abs_ema": round(
                self.error_abs_ema, 4,
            ),
            "bias_ema": round(self.bias_ema, 4),
            "last_update_ts": self.last_update_ts,
        }


@dataclass
class CalibratedPrediction:
    kpi: str
    mean: float
    stdev: float
    calibrated_stdev: float
    samples: int
    bias_adjusted_mean: float
    band: str
    calibration_sample_count: int
    explanation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kpi": self.kpi,
            "mean": round(self.mean, 4),
            "stdev": round(self.stdev, 4),
            "calibrated_stdev": round(
                self.calibrated_stdev, 4,
            ),
            "samples": self.samples,
            "bias_adjusted_mean": round(
                self.bias_adjusted_mean, 4,
            ),
            "band": self.band,
            "calibration_sample_count": (
                self.calibration_sample_count
            ),
            "explanation": self.explanation,
        }


def _band(
    samples: int, stdev: float,
) -> str:
    if samples == 0:
        return "uninformed"
    if stdev <= 0.2:
        return "tight"
    if stdev <= 0.6:
        return "moderate"
    return "loose"


class WorldModelCalibration:
    """Wraps WorldModel with per-KPI prediction-error tracking."""

    def __init__(
        self,
        db_path: str | Path = (
            "data/world_model_calibration.db"
        ),
        *,
        world_model: Any = None,
        widen_factor: float = _DEFAULT_WIDEN_FACTOR,
        now_fn: Any = None,
    ) -> None:
        if widen_factor < 1.0:
            raise ValueError(
                "widen_factor must be ≥ 1.0",
            )
        self._path = Path(db_path)
        self._path.parent.mkdir(
            parents=True, exist_ok=True,
        )
        self._lock = threading.RLock()
        self._world_model = world_model
        self._widen = float(widen_factor)
        self._now_fn = now_fn or time.time
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False,
        )
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Record realised outcome ──────────────────────────

    def record_outcome(
        self,
        kpi: str,
        *,
        predicted: float,
        actual: float,
    ) -> CalibrationRecord:
        if not kpi:
            raise ValueError("kpi required")
        now = float(self._now_fn())
        err = abs(float(actual) - float(predicted))
        bias = float(actual) - float(predicted)
        with self._lock:
            row = self._conn.execute(
                "SELECT sample_count, error_abs_ema, "
                "bias_ema FROM calibration WHERE kpi=?",
                (kpi,),
            ).fetchone()
            if row is None:
                sample_count = 1
                err_ema = err
                bias_val = bias
                self._conn.execute(
                    "INSERT INTO calibration("
                    "kpi, sample_count, error_abs_ema, "
                    "bias_ema, last_update_ts) "
                    "VALUES(?, ?, ?, ?, ?)",
                    (
                        kpi, sample_count,
                        err_ema, bias_val, now,
                    ),
                )
            else:
                sample_count = int(row[0]) + 1
                err_ema = (
                    _EMA_ALPHA * err
                    + (1.0 - _EMA_ALPHA)
                    * float(row[1])
                )
                bias_val = (
                    _EMA_ALPHA * bias
                    + (1.0 - _EMA_ALPHA)
                    * float(row[2])
                )
                self._conn.execute(
                    "UPDATE calibration SET "
                    "sample_count=?, error_abs_ema=?, "
                    "bias_ema=?, last_update_ts=? "
                    "WHERE kpi=?",
                    (
                        sample_count, err_ema, bias_val,
                        now, kpi,
                    ),
                )
            self._conn.commit()
        return CalibrationRecord(
            kpi=kpi,
            sample_count=sample_count,
            error_abs_ema=err_ema,
            bias_ema=bias_val,
            last_update_ts=now,
        )

    # ── Predict (what-if) ────────────────────────────────

    def predict(
        self,
        *,
        action: str,
        context: dict[str, Any] | None = None,
        kpi: str = "roas",
    ) -> CalibratedPrediction:
        ctx = dict(context or {})
        world = self._get_world_model()
        base = None
        if world is not None:
            try:
                from core.brain.world_model import (
                    Context,
                )
                world_ctx = Context(
                    niche=ctx.get("niche", "unknown"),
                    price_band=ctx.get(
                        "price_band", "mid",
                    ),
                    margin_band=ctx.get(
                        "margin_band", "mid",
                    ),
                    copy_tone=ctx.get(
                        "copy_tone", "friendly",
                    ),
                )
                base = world.predict(
                    action=action,
                    context=world_ctx,
                    kpi=kpi,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "world_model.predict failed: %s",
                    exc,
                )
        if base is None:
            mean = 0.0
            stdev = 0.0
            samples = 0
        else:
            mean = float(getattr(base, "mean", 0.0))
            stdev = float(getattr(base, "stdev", 0.0))
            samples = int(getattr(base, "samples", 0))
        cal = self.get(kpi)
        cal_samples = cal.sample_count if cal else 0
        # Widen stdev by EMA of observed error (reality check)
        extra = (
            cal.error_abs_ema if cal else 0.0
        )
        calibrated_stdev = max(
            stdev, stdev * self._widen + extra,
        )
        # Correct systematic bias (add EMA bias to mean)
        bias = cal.bias_ema if cal else 0.0
        bias_adjusted_mean = mean + bias
        band = _band(samples, calibrated_stdev)
        explanation = self._explain(
            action=action,
            kpi=kpi,
            base_mean=mean,
            base_stdev=stdev,
            calibrated_stdev=calibrated_stdev,
            bias=bias,
            samples=samples,
            cal_samples=cal_samples,
        )
        return CalibratedPrediction(
            kpi=kpi,
            mean=mean,
            stdev=stdev,
            calibrated_stdev=calibrated_stdev,
            samples=samples,
            bias_adjusted_mean=bias_adjusted_mean,
            band=band,
            calibration_sample_count=cal_samples,
            explanation=explanation,
        )

    def _explain(
        self,
        *,
        action: str,
        kpi: str,
        base_mean: float,
        base_stdev: float,
        calibrated_stdev: float,
        bias: float,
        samples: int,
        cal_samples: int,
    ) -> str:
        parts = [
            f"action={action} kpi={kpi}",
            (
                f"base: mean {base_mean:.3f} ± "
                f"{base_stdev:.3f} over {samples} samples"
            ),
            (
                f"calibrated stdev: "
                f"{calibrated_stdev:.3f} "
                f"(widen × {self._widen} + "
                f"error EMA)"
            ),
            (
                f"bias correction: "
                f"{bias:+.3f} from "
                f"{cal_samples} realised outcomes"
            ),
        ]
        return " | ".join(parts)

    def _get_world_model(self) -> Any:
        if self._world_model is not None:
            return self._world_model
        try:
            from core.brain.world_model import WorldModel
            self._world_model = WorldModel()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "world_model load failed: %s", exc,
            )
        return self._world_model

    # ── Query ────────────────────────────────────────────

    def get(self, kpi: str) -> CalibrationRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT kpi, sample_count, error_abs_ema, "
                "bias_ema, last_update_ts "
                "FROM calibration WHERE kpi=?",
                (kpi,),
            ).fetchone()
        if row is None:
            return None
        return CalibrationRecord(
            kpi=row[0],
            sample_count=int(row[1]),
            error_abs_ema=float(row[2]),
            bias_ema=float(row[3]),
            last_update_ts=float(row[4]),
        )

    def all_records(self) -> list[CalibrationRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kpi FROM calibration "
                "ORDER BY last_update_ts DESC",
            ).fetchall()
        out: list[CalibrationRecord] = []
        for r in rows:
            rec = self.get(r[0])
            if rec is not None:
                out.append(rec)
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "tracked_kpis": [
                r.kpi for r in self.all_records()
            ],
            "widen_factor": self._widen,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: WorldModelCalibration | None = None
_SINGLETON_LOCK = threading.Lock()


def get_world_model_calibration() -> WorldModelCalibration:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = WorldModelCalibration()
    return _SINGLETON


def reset_world_model_calibration_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            try:
                _SINGLETON.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "reset world_model_calib close: %s",
                    exc,
                )
        _SINGLETON = None
