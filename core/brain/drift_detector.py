"""Drift detector — alert when distributions shift.

The brain trains on historical data; production distributions
shift. A rule that learned "kill audio below ROAS 1.5" can become
systematically wrong when the niche baseline drifts up to ROAS
3.0 without anyone noticing. Surprise (v8-D2) catches individual
outliers; drift catches *population-level* shifts.

DriftDetector keeps a *reference* window (baseline snapshot) and
a *current* window (live). For numerics it runs two tests:

  • Mean shift: standardised |μ_current − μ_reference| / σ_ref.
  • Kolmogorov-Smirnov: max |CDF_ref(x) − CDF_cur(x)|.

For categoricals it uses a Chi-square-style distance:

  Σ (p_cur(k) − p_ref(k))² / (p_ref(k) + ε)

Each comparison returns a 0-1 severity. A Drift event is emitted
when either test exceeds its threshold. Events carry before /
after stats so the owner digest can describe the shift.

Thread-safe, pure stdlib, deterministic. Integrates cleanly with
surprise_detector (fire as `signature=drift:<feature>` outliers)
and outcome_router (emit kind=drift for downstream reactions).
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Kind = Literal["numeric", "categorical"]


@dataclass
class DriftEvent:
    feature: str
    kind: Kind
    severity: float                 # 0..1
    mean_shift_sigma: float | None = None
    ks_statistic: float | None = None
    chi2_distance: float | None = None
    ref_summary: dict[str, Any] = field(default_factory=dict)
    cur_summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "kind": self.kind,
            "severity": round(self.severity, 3),
            "mean_shift_sigma": (
                round(self.mean_shift_sigma, 3)
                if self.mean_shift_sigma is not None else None
            ),
            "ks_statistic": (
                round(self.ks_statistic, 3)
                if self.ks_statistic is not None else None
            ),
            "chi2_distance": (
                round(self.chi2_distance, 3)
                if self.chi2_distance is not None else None
            ),
            "ref_summary": self.ref_summary,
            "cur_summary": self.cur_summary,
        }


# ── Statistical helpers ─────────────────────────────────────

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def ks_statistic(ref: list[float], cur: list[float]) -> float:
    """Two-sample Kolmogorov-Smirnov. Returns max |CDF_ref − CDF_cur|."""
    if not ref or not cur:
        return 0.0
    combined = sorted(set(ref) | set(cur))
    if not combined:
        return 0.0
    def _cdf(xs: list[float], v: float) -> float:
        # fraction of xs ≤ v
        return sum(1 for x in xs if x <= v) / len(xs)
    return max(abs(_cdf(ref, v) - _cdf(cur, v)) for v in combined)


def chi_square_distance(
    ref_counts: dict[str, int], cur_counts: dict[str, int],
) -> float:
    keys = set(ref_counts) | set(cur_counts)
    if not keys:
        return 0.0
    ref_total = sum(ref_counts.values()) or 1
    cur_total = sum(cur_counts.values()) or 1
    eps = 1e-6
    total = 0.0
    for k in keys:
        p_ref = ref_counts.get(k, 0) / ref_total
        p_cur = cur_counts.get(k, 0) / cur_total
        total += ((p_cur - p_ref) ** 2) / (p_ref + eps)
    return total


# ── Detector ────────────────────────────────────────────────

class DriftDetector:
    def __init__(
        self,
        mean_sigma_threshold: float = 2.0,
        ks_threshold: float = 0.25,
        chi2_threshold: float = 0.3,
    ) -> None:
        self._mean_th = float(mean_sigma_threshold)
        self._ks_th = float(ks_threshold)
        self._chi2_th = float(chi2_threshold)
        self._numeric_ref: dict[str, list[float]] = {}
        self._categorical_ref: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()

    # ── Reference windows ───────────────────────────────────

    def set_numeric_reference(
        self, feature: str, values: Iterable[float],
    ) -> None:
        with self._lock:
            self._numeric_ref[feature] = [float(v) for v in values]

    def set_categorical_reference(
        self, feature: str, values: Iterable[Any],
    ) -> None:
        counts: dict[str, int] = {}
        for v in values:
            key = str(v)
            counts[key] = counts.get(key, 0) + 1
        with self._lock:
            self._categorical_ref[feature] = counts

    # ── Checks ──────────────────────────────────────────────

    def check_numeric(
        self, feature: str, values: Iterable[float],
    ) -> DriftEvent | None:
        cur = [float(v) for v in values]
        if not cur:
            return None
        with self._lock:
            ref = list(self._numeric_ref.get(feature, []))
        if not ref:
            return None
        ref_mean, ref_std = _mean(ref), _stdev(ref)
        cur_mean = _mean(cur)
        sigma = (
            abs(cur_mean - ref_mean) / ref_std if ref_std > 0 else 0.0
        )
        ks = ks_statistic(ref, cur)
        severity = max(
            min(1.0, sigma / max(self._mean_th * 2, 1e-6)),
            min(1.0, ks / max(self._ks_th * 2, 1e-6)),
        )
        if sigma < self._mean_th and ks < self._ks_th:
            return None
        return DriftEvent(
            feature=feature, kind="numeric",
            severity=severity,
            mean_shift_sigma=sigma,
            ks_statistic=ks,
            ref_summary={
                "n": len(ref),
                "mean": round(ref_mean, 3),
                "stdev": round(ref_std, 3),
            },
            cur_summary={
                "n": len(cur),
                "mean": round(cur_mean, 3),
                "stdev": round(_stdev(cur), 3),
            },
        )

    def check_categorical(
        self, feature: str, values: Iterable[Any],
    ) -> DriftEvent | None:
        cur_counts: dict[str, int] = {}
        for v in values:
            key = str(v)
            cur_counts[key] = cur_counts.get(key, 0) + 1
        if not cur_counts:
            return None
        with self._lock:
            ref_counts = dict(self._categorical_ref.get(feature, {}))
        if not ref_counts:
            return None
        chi2 = chi_square_distance(ref_counts, cur_counts)
        severity = min(1.0, chi2 / max(self._chi2_th * 2, 1e-6))
        if chi2 < self._chi2_th:
            return None
        return DriftEvent(
            feature=feature, kind="categorical",
            severity=severity,
            chi2_distance=chi2,
            ref_summary={"n": sum(ref_counts.values()),
                          "top": _top_k(ref_counts, 3)},
            cur_summary={"n": sum(cur_counts.values()),
                          "top": _top_k(cur_counts, 3)},
        )

    # ── Full batch ──────────────────────────────────────────

    def check_batch(
        self,
        numeric: dict[str, Iterable[float]] | None = None,
        categorical: dict[str, Iterable[Any]] | None = None,
    ) -> list[DriftEvent]:
        events: list[DriftEvent] = []
        for feat, vals in (numeric or {}).items():
            ev = self.check_numeric(feat, vals)
            if ev is not None:
                events.append(ev)
        for feat, vals in (categorical or {}).items():
            ev = self.check_categorical(feat, vals)
            if ev is not None:
                events.append(ev)
        events.sort(key=lambda e: -e.severity)
        return events

    # ── Introspection ──────────────────────────────────────

    def reference_shapes(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            out: dict[str, dict[str, Any]] = {}
            for f, vals in self._numeric_ref.items():
                out[f] = {
                    "kind": "numeric", "n": len(vals),
                    "mean": round(_mean(vals), 3),
                    "stdev": round(_stdev(vals), 3),
                }
            for f, counts in self._categorical_ref.items():
                out[f] = {
                    "kind": "categorical",
                    "n": sum(counts.values()),
                    "top": _top_k(counts, 3),
                }
            return out


def _top_k(counts: dict[str, int], k: int) -> list[tuple[str, int]]:
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    return items[:k]
