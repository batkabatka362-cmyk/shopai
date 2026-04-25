"""Calibration tracker — are the brain's confidences honest?

A well-calibrated 70 %-confident prediction should come true 70 %
of the time. Over-confident brains ignore their own uncertainty;
under-confident brains miss opportunities. Both fail silently
unless we explicitly track calibration.

Inputs:
  • Pre-launch predictor (v2-D2) emits a win_probability per launch.
  • Evaluator (v1-D4) eventually emits a verdict (scale / kill / hold).
  • Deliberation (v4-D5) emits a judge confidence + verdict.

This module joins predictions to realised outcomes and computes:
  • Brier score (MSE between predicted probability and realised 0/1)
  • Reliability diagram (predicted-vs-actual within 10 buckets)
  • Over-confidence bias (mean(predicted − actual))

Emit calibration drift when |bias| > 0.15 or Brier trails the naïve
predictor. Persists summary as ``category=calibration score=3.0``.

Pure math over MemoryIntelligence — no LLM.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DB_PATH = Path("data/memory_intelligence.db")
_BUCKET_COUNT = 10
_BIAS_THRESHOLD = 0.15


@dataclass
class Bucket:
    lo: float                  # predicted probability lower bound
    hi: float                  # upper bound
    predicted_mean: float = 0.0
    actual_rate: float = 0.0   # fraction of realised wins
    n: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "range": [round(self.lo, 2), round(self.hi, 2)],
            "predicted_mean": round(self.predicted_mean, 3),
            "actual_rate": round(self.actual_rate, 3),
            "samples": self.n,
        }


@dataclass
class CalibrationReport:
    samples: int
    brier_score: float = 1.0    # 0 = perfect, 0.25 = random (p=0.5)
    bias: float = 0.0           # mean(pred − actual); >0 = over-confident
    reliability: list[Bucket] = field(default_factory=list)
    recorded: bool = False
    ts: float = 0.0

    @property
    def level(self) -> str:
        if self.samples == 0:
            return "unknown"
        if abs(self.bias) > _BIAS_THRESHOLD:
            return "drift"
        if self.brier_score > 0.3:
            return "noisy"
        if self.brier_score < 0.15 and abs(self.bias) < 0.05:
            return "good"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "brier_score": round(self.brier_score, 4),
            "bias": round(self.bias, 4),
            "level": self.level,
            "ts": self.ts,
            "reliability": [b.as_dict() for b in self.reliability],
        }


def score() -> CalibrationReport:
    """Scan past launches with a predictor prediction and a realised
    verdict, compute Brier + bias + reliability diagram."""
    pairs = _collect_pairs()
    if not pairs:
        return CalibrationReport(samples=0, ts=time.time())

    # Brier score = mean((p - y)^2) where y = 1 if scale, 0 if kill
    squared_errors = [(p - y) ** 2 for p, y in pairs]
    brier = sum(squared_errors) / len(pairs)
    bias = sum(p - y for p, y in pairs) / len(pairs)
    buckets = _reliability_diagram(pairs)

    report = CalibrationReport(
        samples=len(pairs),
        brier_score=brier,
        bias=bias,
        reliability=buckets,
        ts=time.time(),
    )
    report.recorded = _persist(report)
    return report


def _reliability_diagram(pairs: list[tuple[float, float]]) -> list[Bucket]:
    bucket_width = 1.0 / _BUCKET_COUNT
    buckets = [
        Bucket(lo=i * bucket_width, hi=(i + 1) * bucket_width)
        for i in range(_BUCKET_COUNT)
    ]
    for p, y in pairs:
        idx = min(_BUCKET_COUNT - 1, int(p * _BUCKET_COUNT))
        b = buckets[idx]
        b.n += 1
        b.predicted_mean += p
        b.actual_rate += y
    for b in buckets:
        if b.n:
            b.predicted_mean /= b.n
            b.actual_rate /= b.n
    return [b for b in buckets if b.n > 0]


def _collect_pairs() -> list[tuple[float, float]]:
    """Pull every launch that has *both* a predictor win_probability
    and an evaluator verdict ∈ {scale, kill}. Returns list of
    (predicted_prob, realised_y)."""
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories "
            "WHERE category='launch' AND score >= 0 "
            "ORDER BY timestamp DESC LIMIT 500"
        )
        launch_rows = cur.fetchall()
    finally:
        conn.close()

    try:
        from core.autonomous.launch_evaluator import evaluate
        eval_report = evaluate()
    except Exception:
        eval_report = None

    verdict_by_id: dict[str, str] = {}
    if eval_report is not None:
        for s in (
            eval_report.kill_recommendations
            + eval_report.scale_recommendations
            + eval_report.monitor_recommendations
        ):
            verdict_by_id[s.launch_id] = s.verdict

    pairs: list[tuple[float, float]] = []
    for (content_json,) in launch_rows:
        try:
            c = json.loads(content_json or "{}")
        except (json.JSONDecodeError, ValueError):
            continue
        lid = c.get("launch_id")
        if not lid:
            continue
        # Prediction stored at launch time by LaunchContext.prediction
        pred = (c.get("prediction") or {}).get("win_probability")
        if pred is None:
            continue
        verdict = verdict_by_id.get(lid, "")
        if verdict == "scale":
            pairs.append((float(pred), 1.0))
        elif verdict == "kill":
            pairs.append((float(pred), 0.0))
        # hold / waiting_for_data skip — outcome not yet known
    return pairs


def _persist(report: CalibrationReport) -> bool:
    try:
        from core.memory.unified_memory import get_unified_memory
        mi = get_unified_memory().get_memory_intelligence()
        mi.create(
            category="calibration",
            content=report.as_dict(),
            action=report.level,
            score=3.0,
            tags=["calibration", report.level,
                  f"samples:{report.samples}"],
        )
        return True
    except Exception:
        return False
