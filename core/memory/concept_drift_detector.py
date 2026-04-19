"""Concept drift detector — is the world still the world I learned?

Models that were trained on yesterday's distribution stop working
when the distribution shifts (new traffic source, new season, price
war, ad platform update). Silent drift is the single biggest reason
data-driven rules go stale. This detector watches a feature stream
and raises an alert when the recent window diverges from the baseline.

Two complementary tests — pick by feature kind at call time:

  • Numeric features  — compute running mean + variance via Welford
    over a baseline and a recent window, then Population Stability
    Index (PSI) over quantile bins.
  • Categorical        — PSI over categorical buckets (same formula,
    distributions normalised to probabilities).

PSI interpretation (industry standard):
  • < 0.1           — no meaningful shift
  • 0.1 ≤ p < 0.2   — moderate shift, consider retraining
  • ≥ 0.2           — significant shift, definitely retrain

Usage:

    d = ConceptDriftDetector()
    for row in baseline:
        d.observe_numeric("cpm", row["cpm"], phase="baseline")
    for row in live:
        d.observe_numeric("cpm", row["cpm"], phase="recent")

    report = d.check("cpm")   # → DriftReport

Pure stdlib. In-memory accumulation. Deterministic.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

Phase = Literal["baseline", "recent"]
Severity = Literal["none", "moderate", "significant"]


_EPS = 1e-6


@dataclass
class DriftReport:
    feature: str
    kind: Literal["numeric", "categorical", "insufficient"]
    psi: float
    severity: Severity
    n_baseline: int
    n_recent: int
    per_bin: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "kind": self.kind,
            "psi": round(self.psi, 4),
            "severity": self.severity,
            "n_baseline": self.n_baseline,
            "n_recent": self.n_recent,
            "per_bin": self.per_bin,
            "note": self.note,
        }


# ── PSI utilities ─────────────────────────────────────────

def _psi(
    baseline_counts: dict[str, int],
    recent_counts: dict[str, int],
) -> tuple[float, list[dict[str, Any]]]:
    """Population Stability Index across matched bins.

    Σ (r_i − b_i) × ln(r_i / b_i)  where r_i, b_i are proportions.
    Floors zero-mass bins at EPS to avoid log(0).
    """
    keys = sorted(set(baseline_counts) | set(recent_counts))
    total_b = sum(baseline_counts.get(k, 0) for k in keys) or 1
    total_r = sum(recent_counts.get(k, 0) for k in keys) or 1
    psi = 0.0
    per_bin: list[dict[str, Any]] = []
    for k in keys:
        b = max(_EPS, baseline_counts.get(k, 0) / total_b)
        r = max(_EPS, recent_counts.get(k, 0) / total_r)
        contrib = (r - b) * math.log(r / b)
        psi += contrib
        per_bin.append({
            "bin": k,
            "baseline_share": round(b, 4),
            "recent_share": round(r, 4),
            "psi_contrib": round(contrib, 4),
        })
    return psi, per_bin


def _severity(psi: float) -> Severity:
    if psi < 0.1:
        return "none"
    if psi < 0.2:
        return "moderate"
    return "significant"


def _quantile_edges(
    values: list[float], n_bins: int = 10,
) -> list[float]:
    if not values:
        return []
    svalues = sorted(values)
    n = len(svalues)
    if n_bins < 2:
        n_bins = 2
    edges: list[float] = []
    for i in range(1, n_bins):
        idx = min(n - 1, max(0, int(i * n / n_bins)))
        edges.append(svalues[idx])
    # Deduplicate tied edges
    out: list[float] = []
    for e in edges:
        if not out or e > out[-1]:
            out.append(e)
    return out


def _bin_label(i: int) -> str:
    return f"q{i:02d}"


def _bin_numeric(
    values: list[float], edges: list[float],
) -> dict[str, int]:
    out: Counter[str] = Counter()
    for v in values:
        idx = 0
        for e in edges:
            if v <= e:
                break
            idx += 1
        out[_bin_label(idx)] += 1
    return dict(out)


# ── Detector ──────────────────────────────────────────────

class ConceptDriftDetector:
    def __init__(
        self,
        *,
        min_baseline: int = 20,
        min_recent: int = 10,
        n_bins: int = 10,
    ) -> None:
        if min_baseline <= 0 or min_recent <= 0 or n_bins <= 1:
            raise ValueError("config thresholds must be positive")
        self._min_baseline = int(min_baseline)
        self._min_recent = int(min_recent)
        self._n_bins = int(n_bins)
        self._numeric: dict[str, dict[Phase, list[float]]] = (
            defaultdict(lambda: {"baseline": [], "recent": []})
        )
        self._categorical: dict[str, dict[Phase, Counter[str]]] = (
            defaultdict(lambda: {
                "baseline": Counter(), "recent": Counter(),
            })
        )

    def observe_numeric(
        self, feature: str, value: float, phase: Phase,
    ) -> None:
        if phase not in ("baseline", "recent"):
            raise ValueError("phase must be baseline or recent")
        self._numeric[feature][phase].append(float(value))

    def observe_categorical(
        self, feature: str, value: str, phase: Phase,
    ) -> None:
        if phase not in ("baseline", "recent"):
            raise ValueError("phase must be baseline or recent")
        self._categorical[feature][phase][str(value)] += 1

    # ── Checks ─────────────────────────────────────────────

    def check(self, feature: str) -> DriftReport:
        if feature in self._numeric:
            return self._check_numeric(feature)
        if feature in self._categorical:
            return self._check_categorical(feature)
        return DriftReport(
            feature=feature, kind="insufficient",
            psi=0.0, severity="none",
            n_baseline=0, n_recent=0,
            note="no observations",
        )

    def _check_numeric(self, feature: str) -> DriftReport:
        data = self._numeric[feature]
        b, r = data["baseline"], data["recent"]
        if len(b) < self._min_baseline or len(r) < self._min_recent:
            return DriftReport(
                feature=feature, kind="insufficient",
                psi=0.0, severity="none",
                n_baseline=len(b), n_recent=len(r),
                note=(
                    f"need ≥ {self._min_baseline} baseline "
                    f"and ≥ {self._min_recent} recent"
                ),
            )
        edges = _quantile_edges(b, n_bins=self._n_bins)
        b_counts = _bin_numeric(b, edges)
        r_counts = _bin_numeric(r, edges)
        psi, per_bin = _psi(b_counts, r_counts)
        return DriftReport(
            feature=feature, kind="numeric",
            psi=psi, severity=_severity(psi),
            n_baseline=len(b), n_recent=len(r),
            per_bin=per_bin,
        )

    def _check_categorical(self, feature: str) -> DriftReport:
        data = self._categorical[feature]
        b, r = data["baseline"], data["recent"]
        nb, nr = sum(b.values()), sum(r.values())
        if nb < self._min_baseline or nr < self._min_recent:
            return DriftReport(
                feature=feature, kind="insufficient",
                psi=0.0, severity="none",
                n_baseline=nb, n_recent=nr,
                note=(
                    f"need ≥ {self._min_baseline} baseline "
                    f"and ≥ {self._min_recent} recent"
                ),
            )
        psi, per_bin = _psi(dict(b), dict(r))
        return DriftReport(
            feature=feature, kind="categorical",
            psi=psi, severity=_severity(psi),
            n_baseline=nb, n_recent=nr,
            per_bin=per_bin,
        )

    def check_all(self) -> list[DriftReport]:
        reports: list[DriftReport] = []
        for f in self._numeric:
            reports.append(self._check_numeric(f))
        for f in self._categorical:
            reports.append(self._check_categorical(f))
        reports.sort(key=lambda r: -r.psi)
        return reports

    def reset(self, feature: str | None = None) -> None:
        if feature is None:
            self._numeric.clear()
            self._categorical.clear()
        else:
            self._numeric.pop(feature, None)
            self._categorical.pop(feature, None)

    def features(self) -> list[str]:
        return sorted(
            set(self._numeric) | set(self._categorical),
        )

    def summary(self) -> dict[str, Any]:
        reports = self.check_all()
        shifted = [
            r for r in reports if r.severity != "none"
            and r.kind != "insufficient"
        ]
        return {
            "features_tracked": len(self.features()),
            "shifted": [r.as_dict() for r in shifted],
            "worst_psi": (
                round(reports[0].psi, 4) if reports else 0.0
            ),
        }
