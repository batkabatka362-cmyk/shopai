"""Memory compressor — distill aging events into compact summaries.

consolidation (v5) already compresses old events, but it operates
on single tables. memory_compressor goes further: it groups
*semantically similar* events across categories by feature
signature and emits one *summary* row that captures the
distribution stats of the group. The original rows are then
candidates for deletion by data_housekeeper.

Example: 500 order events from audio/mid/$20-$30 band get
summarised into a single row carrying (n=500, mean_revenue=$27,
refund_rate=3.1%, last_seen=...). Subsequent retrieval queries
returning results without traversing those 500 — huge latency
win at scale.

APIs:

  compress(rows, fields, min_group=20)
      → list[CompressedSummary]
  rehydrate(summary, row)
      → re-expand a specific example into a full dict
      (for debate / counterfactual drill-down)

Deterministic grouping via feature signatures. Supports numeric
and categorical fields. Pure stdlib.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class NumericStats:
    n: int = 0
    min: float = float("inf")
    max: float = float("-inf")
    mean: float = 0.0
    stdev: float = 0.0
    m2: float = 0.0        # for Welford

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "min": round(self.min, 3) if self.n else None,
            "max": round(self.max, 3) if self.n else None,
            "mean": round(self.mean, 3),
            "stdev": round(self.stdev, 3),
        }


@dataclass
class CompressedSummary:
    signature: str
    n_rows: int
    group_key: dict[str, Any]
    numeric_fields: dict[str, NumericStats] = field(
        default_factory=dict,
    )
    categorical_fields: dict[str, dict[str, int]] = field(
        default_factory=dict,
    )
    sample_ids: list[str] = field(default_factory=list)
    time_range: tuple[float, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "n_rows": self.n_rows,
            "group_key": self.group_key,
            "numeric_fields": {
                k: v.as_dict() for k, v in self.numeric_fields.items()
            },
            "categorical_fields": self.categorical_fields,
            "sample_ids": self.sample_ids,
            "time_range": (
                [round(self.time_range[0], 2),
                 round(self.time_range[1], 2)]
                if self.time_range else None
            ),
        }


# ── Helpers ────────────────────────────────────────────────

def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _signature(group_key: dict[str, Any]) -> str:
    canonical = json.dumps(group_key, sort_keys=True, default=str)
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


# ── Compressor ──────────────────────────────────────────────

def compress(
    rows: Iterable[dict[str, Any]],
    group_fields: Iterable[str],
    *,
    min_group: int = 20,
    sample_limit: int = 5,
) -> list[CompressedSummary]:
    """Group rows by the tuple of values at ``group_fields`` and emit
    one summary per group with size ≥ ``min_group``. Groups below
    threshold are returned as empty (caller keeps the raw rows)."""
    group_fields = list(group_fields)
    if not group_fields:
        return []
    buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(f) for f in group_fields)
        buckets[key].append(row)
    summaries: list[CompressedSummary] = []
    for key, group in buckets.items():
        if len(group) < min_group:
            continue
        summary = _summarise(group_fields, key, group,
                              sample_limit=sample_limit)
        summaries.append(summary)
    summaries.sort(key=lambda s: -s.n_rows)
    return summaries


def _summarise(
    group_fields: list[str],
    key: tuple,
    group: list[dict[str, Any]],
    sample_limit: int,
) -> CompressedSummary:
    group_key = {f: k for f, k in zip(group_fields, key)}
    numeric: dict[str, NumericStats] = defaultdict(NumericStats)
    categorical: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int),
    )
    tss: list[float] = []
    for row in group:
        ts = row.get("ts") or row.get("timestamp")
        if _is_numeric(ts):
            tss.append(float(ts))
        for k, v in row.items():
            if k in group_fields or v is None:
                continue
            if _is_numeric(v):
                s = numeric[k]
                val = float(v)
                s.n += 1
                s.min = min(s.min, val)
                s.max = max(s.max, val)
                delta = val - s.mean
                s.mean += delta / s.n
                delta2 = val - s.mean
                s.m2 += delta * delta2
            elif isinstance(v, str):
                categorical[k][v] += 1
    # Finalise stdev
    for s in numeric.values():
        if s.n >= 2:
            import math
            s.stdev = math.sqrt(s.m2 / (s.n - 1))
    # Sample ids (first N)
    sample_ids: list[str] = []
    for row in group[:sample_limit]:
        rid = row.get("id") or row.get("row_id") or ""
        if rid:
            sample_ids.append(str(rid))
    time_range = (min(tss), max(tss)) if tss else None
    return CompressedSummary(
        signature=_signature(group_key),
        n_rows=len(group),
        group_key=group_key,
        numeric_fields=dict(numeric),
        categorical_fields={
            k: dict(v) for k, v in categorical.items()
        },
        sample_ids=sample_ids,
        time_range=time_range,
    )


# ── Rehydrate ──────────────────────────────────────────────

def rehydrate(
    summary: CompressedSummary, row_id: str,
    raw_rows: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the original row from raw_rows that matches both the
    group key and ``row_id``. Useful for counterfactual drill-down
    after compression."""
    row_id = str(row_id)
    for r in raw_rows:
        rid = str(r.get("id") or r.get("row_id") or "")
        if rid != row_id:
            continue
        match = all(
            r.get(k) == v
            for k, v in summary.group_key.items()
        )
        if match:
            return r
    return None
