"""Funnel analyzer — spot where conversions leak.

session_tracker (v14-D2) gives us per-actor event streams. Funnel
analysis turns those into a cross-actor conversion funnel:

    visit → view_product → add_to_cart → checkout → purchase

and flags the worst drop-off step. That's the single highest-
value diagnostic an e-commerce brain can produce — fix the
biggest leak and revenue jumps measurably.

FunnelAnalyzer takes a list of Session objects (or the dict
equivalents) plus an ordered list of step names. It computes:

  • per-step absolute counts
  • per-step conversion_rate vs previous step
  • step-to-step drop_rate
  • overall conversion (first → last)
  • the bottleneck step (biggest drop_rate)

Also supports *segmented* funnels: slice by niche / source / etc.,
run the same funnel per segment, and return the per-segment
bottleneck so the owner can prioritise fixes.

Pure stdlib. Zero LLM. Deterministic.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class FunnelStep:
    name: str
    count: int = 0
    conversion_rate: float = 0.0     # of previous step
    drop_rate: float = 0.0           # 1 − conversion_rate

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "count": self.count,
            "conversion_rate": round(self.conversion_rate, 3),
            "drop_rate": round(self.drop_rate, 3),
        }


@dataclass
class FunnelReport:
    steps: list[FunnelStep] = field(default_factory=list)
    total_sessions: int = 0
    end_to_end_conversion: float = 0.0
    bottleneck_step: str | None = None
    bottleneck_drop_rate: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.as_dict() for s in self.steps],
            "total_sessions": self.total_sessions,
            "end_to_end_conversion": round(self.end_to_end_conversion, 3),
            "bottleneck_step": self.bottleneck_step,
            "bottleneck_drop_rate": round(self.bottleneck_drop_rate, 3),
        }


# ── Core analyser ───────────────────────────────────────────

def analyse(
    sessions: Iterable[Any],
    steps: list[str],
) -> FunnelReport:
    """Compute a funnel over the step names.

    ``sessions`` can be a list of Session objects (with .events) or
    dicts. A session *counts* toward step N if any of its events
    has that kind AND the session already counted for every earlier
    step. This enforces the classic funnel invariant (step-N ≤
    step-N-1)."""
    if not steps:
        return FunnelReport()
    steps = [s.strip() for s in steps if s and s.strip()]
    if not steps:
        return FunnelReport()
    counts = [0] * len(steps)
    total = 0
    for sess in sessions:
        total += 1
        kinds = _event_kinds(sess)
        reached = 0
        for idx, step in enumerate(steps):
            if step in kinds:
                reached = idx + 1
            else:
                break
        for i in range(reached):
            counts[i] += 1
    step_objs: list[FunnelStep] = []
    for idx, name in enumerate(steps):
        prev = counts[idx - 1] if idx > 0 else counts[0] or 1
        rate = counts[idx] / prev if prev > 0 else 0.0
        # First step's "conversion" is just the entry rate into the
        # funnel relative to total sessions — clamp at 1.0.
        if idx == 0 and total > 0:
            rate = counts[idx] / total
        step_objs.append(FunnelStep(
            name=name, count=counts[idx],
            conversion_rate=rate, drop_rate=1.0 - rate,
        ))
    # Overall conversion
    end_to_end = (
        counts[-1] / total if total > 0 else 0.0
    )
    # Bottleneck = largest drop between consecutive steps
    bottleneck_name: str | None = None
    bottleneck_drop = 0.0
    for idx in range(1, len(step_objs)):
        if step_objs[idx].drop_rate > bottleneck_drop:
            bottleneck_drop = step_objs[idx].drop_rate
            bottleneck_name = step_objs[idx].name
    return FunnelReport(
        steps=step_objs,
        total_sessions=total,
        end_to_end_conversion=end_to_end,
        bottleneck_step=bottleneck_name,
        bottleneck_drop_rate=bottleneck_drop,
    )


# ── Segment analyser ────────────────────────────────────────

def analyse_segmented(
    sessions: Iterable[Any],
    steps: list[str],
    *,
    segment_key: str,
) -> dict[str, FunnelReport]:
    buckets: dict[str, list[Any]] = defaultdict(list)
    for sess in sessions:
        key = _segment_of(sess, segment_key)
        buckets[key].append(sess)
    return {k: analyse(items, steps) for k, items in buckets.items()}


# ── Helpers ────────────────────────────────────────────────

def _event_kinds(sess: Any) -> set[str]:
    events = getattr(sess, "events", None)
    if events is None and isinstance(sess, dict):
        events = sess.get("events", [])
    if events is None:
        return set()
    out: set[str] = set()
    for e in events:
        if hasattr(e, "kind"):
            out.add(e.kind)
        elif isinstance(e, dict):
            out.add(str(e.get("kind", "")))
    return {k for k in out if k}


def _segment_of(sess: Any, key: str) -> str:
    events = getattr(sess, "events", None)
    if events is None and isinstance(sess, dict):
        events = sess.get("events", [])
    if events is None:
        return "unknown"
    for e in events:
        meta = getattr(e, "meta", None)
        if meta is None and isinstance(e, dict):
            meta = e.get("meta", {})
        if isinstance(meta, dict) and key in meta:
            v = meta.get(key)
            if v is not None:
                return str(v)
    # Fallback: session-level attribute
    if hasattr(sess, key):
        return str(getattr(sess, key))
    if isinstance(sess, dict) and key in sess:
        return str(sess[key])
    return "unknown"


def best_drop(segmented: dict[str, FunnelReport]) -> tuple[str, str, float]:
    """Return (segment, bottleneck_step, drop_rate) with the worst
    leak across all segments."""
    worst_segment = ""
    worst_step = ""
    worst_rate = 0.0
    for seg, report in segmented.items():
        if report.bottleneck_drop_rate > worst_rate:
            worst_rate = report.bottleneck_drop_rate
            worst_segment = seg
            worst_step = report.bottleneck_step or ""
    return worst_segment, worst_step, worst_rate
