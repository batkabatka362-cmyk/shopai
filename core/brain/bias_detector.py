"""Bias detector — over-representation in decisions or outcomes.

A brain that learns from history will replicate history's bias
unless someone flags it. If 90% of launches the owner approved
were audio-niche, the brain will over-bet audio until audio
saturates. bias_detector measures that distributional skew
against either a reference baseline or a uniform expectation.

Given a set of decision records labelled by attribute (niche,
tone, price_band, action, segment), the detector reports:

  • share        — fraction of decisions at each value
  • expected     — baseline share (uniform OR caller-supplied)
  • disparity    — share − expected
  • severity     — high (|disparity| ≥ 0.2) / medium (≥ 0.1) / low
  • sample_size  — count per value (caveat on small samples)

APIs:

  measure(records, attribute, baseline=None)
      → BiasReport
  compare(records, group_key, outcome_key)
      → per-group success-rate divergence (for outcome-level bias)

Pure stdlib. Deterministic.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Severity = Literal["high", "medium", "low"]


@dataclass
class ValueSlice:
    value: str
    share: float
    expected: float
    disparity: float
    sample_size: int
    severity: Severity

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "share": round(self.share, 3),
            "expected": round(self.expected, 3),
            "disparity": round(self.disparity, 3),
            "sample_size": self.sample_size,
            "severity": self.severity,
        }


@dataclass
class BiasReport:
    attribute: str
    total: int
    slices: list[ValueSlice] = field(default_factory=list)

    @property
    def worst(self) -> ValueSlice | None:
        if not self.slices:
            return None
        return max(self.slices, key=lambda s: abs(s.disparity))

    def as_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "total": self.total,
            "slices": [s.as_dict() for s in self.slices],
            "worst": self.worst.value if self.worst else None,
        }


# ── Measure ────────────────────────────────────────────────

def _severity(disparity: float) -> Severity:
    d = abs(disparity)
    if d >= 0.2:
        return "high"
    if d >= 0.1:
        return "medium"
    return "low"


def measure(
    records: Iterable[dict[str, Any]],
    attribute: str,
    baseline: dict[str, float] | None = None,
) -> BiasReport:
    """Measure over-representation of values for ``attribute``.

    baseline is an optional {value: expected_fraction} dict. If
    omitted, expected = 1/distinct_values (uniform)."""
    counts: Counter[str] = Counter()
    for r in records:
        if not isinstance(r, dict):
            continue
        v = r.get(attribute)
        if v is None:
            continue
        counts[str(v)] += 1
    total = sum(counts.values())
    if total == 0:
        return BiasReport(attribute=attribute, total=0)
    distinct = len(counts)
    default_expected = 1.0 / distinct if distinct else 0.0
    slices: list[ValueSlice] = []
    # Use baseline keys too so we can flag categories we *should*
    # have but didn't.
    keys = set(counts.keys())
    if baseline:
        keys |= set(baseline.keys())
    for value in sorted(keys):
        sample = counts.get(value, 0)
        share = sample / total
        expected = (
            baseline.get(value, default_expected)
            if baseline else default_expected
        )
        disparity = share - expected
        slices.append(ValueSlice(
            value=value,
            share=share,
            expected=expected,
            disparity=disparity,
            sample_size=sample,
            severity=_severity(disparity),
        ))
    # Sort by |disparity| descending — worst offender first
    slices.sort(key=lambda s: -abs(s.disparity))
    return BiasReport(
        attribute=attribute,
        total=total,
        slices=slices,
    )


# ── Outcome-level comparison ────────────────────────────────

@dataclass
class GroupPerformance:
    group: str
    n: int
    success_rate: float
    vs_global_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "n": self.n,
            "success_rate": round(self.success_rate, 3),
            "vs_global_delta": round(self.vs_global_delta, 3),
        }


def compare(
    records: Iterable[dict[str, Any]],
    group_key: str,
    outcome_key: str = "success",
) -> list[GroupPerformance]:
    """Group records by ``group_key`` and compute success rate per
    group plus its delta vs the global average. Useful to detect
    outcome-level bias (e.g. 'fashion orders succeed at 40% vs
    global 65%')."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records = [r for r in records if isinstance(r, dict)]
    for r in records:
        key = r.get(group_key)
        if key is None:
            continue
        groups[str(key)].append(r)
    total = sum(len(rs) for rs in groups.values())
    if total == 0:
        return []
    global_success = sum(
        1 for rs in groups.values() for r in rs
        if bool(r.get(outcome_key))
    ) / total
    out: list[GroupPerformance] = []
    for group, rs in groups.items():
        n = len(rs)
        if n == 0:
            continue
        succ = sum(1 for r in rs if bool(r.get(outcome_key)))
        rate = succ / n
        out.append(GroupPerformance(
            group=group, n=n,
            success_rate=rate,
            vs_global_delta=rate - global_success,
        ))
    out.sort(key=lambda g: -abs(g.vs_global_delta))
    return out
