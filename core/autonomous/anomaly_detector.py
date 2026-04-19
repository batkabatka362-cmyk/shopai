"""Anomaly detector — per-niche baseline deviations.

Trend detector (v2-D2) flags *trajectory* changes. Anomaly detector
flags *value* deviations: a launch with ROAS 0.4 in a niche whose
median is 2.1 is anomalous today, regardless of its trajectory.

Algorithm:

  1. Pull last 60 days of launch snapshots (order + verdict data via
     the evaluator).
  2. For each niche compute (mean, stddev) of ROAS, AOV, order_count
     separately.
  3. For every active launch, z-score each metric against its niche
     baseline.
  4. |z| ≥ 2 → emit a ``category=anomaly score=4.0`` memory event
     with the offending launch id and the deviating metric so
     downstream consumers (causal_inference, oracle) can reference
     it.

Pure statistics — no LLM, O(N) per pass. Baselines are recomputed
each cycle so the tuner gets fresh evidence after self-critique
reweights.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


_MIN_SAMPLES_PER_NICHE = 5
_Z_THRESHOLD = 2.0
_METRICS = ("estimated_roas", "aov", "order_count")


@dataclass
class Anomaly:
    launch_id: str
    niche: str
    metric: str
    value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    direction: str          # "above" | "below"

    def as_dict(self) -> dict[str, Any]:
        return {
            "launch_id": self.launch_id,
            "niche": self.niche,
            "metric": self.metric,
            "value": round(self.value, 3),
            "baseline_mean": round(self.baseline_mean, 3),
            "baseline_stddev": round(self.baseline_stddev, 3),
            "z_score": round(self.z_score, 2),
            "direction": self.direction,
        }


@dataclass
class AnomalyReport:
    checked: int = 0
    anomalies: list[Anomaly] = field(default_factory=list)
    baselines: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)
    recorded: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "recorded": self.recorded,
            "anomaly_count": len(self.anomalies),
            "anomalies": [a.as_dict() for a in self.anomalies],
            "baselines": self.baselines,
        }


def scan() -> AnomalyReport:
    """Run one full anomaly pass. Never raises."""
    try:
        launches = _load_launches()
    except Exception:
        return AnomalyReport()
    if not launches:
        return AnomalyReport()

    baselines = _compute_baselines(launches)
    report = AnomalyReport(baselines=baselines)

    for l in launches:
        niche = l.get("niche") or ""
        if niche not in baselines:
            continue
        report.checked += 1
        for metric in _METRICS:
            value = float(l.get(metric) or 0)
            base = baselines[niche].get(metric) or {}
            mean = base.get("mean", 0.0)
            stddev = base.get("stddev", 0.0)
            if stddev <= 1e-6:
                continue
            z = (value - mean) / stddev
            if abs(z) < _Z_THRESHOLD:
                continue
            anomaly = Anomaly(
                launch_id=l["launch_id"],
                niche=niche,
                metric=metric,
                value=value,
                baseline_mean=mean,
                baseline_stddev=stddev,
                z_score=z,
                direction="above" if z > 0 else "below",
            )
            report.anomalies.append(anomaly)
            if _persist(anomaly):
                report.recorded += 1
    return report


def _load_launches() -> list[dict[str, Any]]:
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
    except Exception:
        return []
    from core.autonomous.self_critic import _niche_map
    niches = _niche_map(limit=500)
    out: list[dict[str, Any]] = []
    buckets = (
        report.kill_recommendations
        + report.scale_recommendations
        + report.monitor_recommendations
    )
    for s in buckets:
        out.append({
            "launch_id": s.launch_id,
            "niche": niches.get(s.launch_id, ""),
            "estimated_roas": s.estimated_roas,
            "aov": s.aov,
            "order_count": float(s.order_count),
            "verdict": s.verdict,
        })
    return out


def _compute_baselines(launches: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    groups: dict[str, dict[str, list[float]]] = {}
    for l in launches:
        niche = l.get("niche") or ""
        if not niche:
            continue
        niche_bucket = groups.setdefault(niche, {m: [] for m in _METRICS})
        for m in _METRICS:
            v = l.get(m)
            if isinstance(v, (int, float)):
                niche_bucket[m].append(float(v))
    out: dict[str, dict[str, dict[str, float]]] = {}
    for niche, metrics in groups.items():
        any_stats = False
        per_metric: dict[str, dict[str, float]] = {}
        for m, values in metrics.items():
            if len(values) < _MIN_SAMPLES_PER_NICHE:
                continue
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / len(values)
            stddev = math.sqrt(var) if var > 0 else 0.0
            per_metric[m] = {
                "mean": mean,
                "stddev": stddev,
                "samples": float(len(values)),
            }
            any_stats = True
        if any_stats:
            out[niche] = per_metric
    return out


def _persist(anomaly: Anomaly) -> bool:
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mi.create(
            category="anomaly",
            content=anomaly.as_dict(),
            action=f"{anomaly.metric}_{anomaly.direction}",
            score=4.0,
            tags=[
                "anomaly",
                anomaly.direction,
                anomaly.metric,
                anomaly.niche,
                f"launch:{anomaly.launch_id}",
            ],
        )
        return True
    except Exception:
        return False
