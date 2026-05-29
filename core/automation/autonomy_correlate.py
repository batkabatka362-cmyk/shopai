"""Autonomy correlation (W721): pairwise domain fire correlation.

Phase 33's recommendations answer "what should I focus on
first?". `autonomy-correlate` answers a different operator
question: "which pairs of domains tend to fire TOGETHER?"

Useful for pattern detection:
  - Expected correlations (fulfillment + inventory both
    fire when an order is placed) -- nothing to investigate.
  - Unexpected correlations (e.g. customer_outreach +
    discount_cleanup correlate strongly) -- why? maybe
    a shared upstream trigger.
  - Anti-correlations (X fires + Y never fires in same
    window) -- might indicate a missing engine pipeline.

Algorithm:
  1. Pick a lookback period (default 168h = 7 days).
  2. Bucket the lookback into B-hour windows (default 24h).
  3. For each domain, collect the SET of buckets in which it
     fired at least once.
  4. For each pair (a, b): compute Jaccard similarity =
     |buckets_a ∩ buckets_b| / |buckets_a ∪ buckets_b|.
  5. Rank pairs by Jaccard desc.

Jaccard = 0.0: never fired in the same bucket.
Jaccard = 1.0: fired in EXACTLY the same buckets.
Jaccard = 0.5: half of their fired buckets are shared.

Pairs where both domains have ZERO fires are excluded (no
signal). Pairs where one domain has zero are jaccard=0
(perfectly anti-correlated, but uninformative on idle branch).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from importlib import import_module

logger = logging.getLogger(__name__)


@dataclass
class CorrelationPair:
    domain_a: str
    domain_b: str
    buckets_a: int           # # buckets where a fired
    buckets_b: int           # # buckets where b fired
    shared: int              # # buckets where BOTH fired
    union: int               # # buckets where EITHER fired
    jaccard: float = 0.0


@dataclass
class CorrelationReport:
    window_hours: float      # lookback total
    bucket_hours: float      # bucket width
    bucket_count: int        # ceil(window_hours / bucket_hours)
    store_id: str | None = None
    pairs: list[CorrelationPair] = field(default_factory=list)
    active_domain_count: int = 0    # domains with > 0 fires


def _domain_event_buckets(
    pkg: str, log_modname: str, fn_name: str,
    window_hours: float, bucket_hours: float,
    store_id: str | None,
) -> set[int]:
    """Return the set of bucket indices (0..N-1) in which the
    domain fired at least one event with applied=True."""
    try:
        mod = import_module(f"engines.{pkg}.{log_modname}")
    except Exception:  # noqa: BLE001
        return set()
    fn = getattr(mod, fn_name, None)
    if fn is None:
        return set()
    try:
        try:
            rows = fn(
                window_hours=window_hours, store_id=store_id,
            )
        except TypeError:
            rows = fn(window_hours=window_hours)
    except Exception:  # noqa: BLE001
        return set()

    now = time.time()
    window_seconds = window_hours * 3600.0
    bucket_seconds = bucket_hours * 3600.0
    start = now - window_seconds
    buckets: set[int] = set()
    for r in rows:
        if r.get("applied") is not True:
            continue
        # Try common timestamp fields
        ts_val = (
            r.get("recorded_at")
            or r.get("timestamp")
            or r.get("created_at")
        )
        if ts_val is None:
            continue
        try:
            ts_f = float(ts_val)
        except (TypeError, ValueError):
            continue
        if ts_f < start or ts_f > now:
            continue
        idx = int((ts_f - start) / bucket_seconds)
        buckets.add(idx)
    return buckets


def run_autonomy_correlate(
    *,
    window_hours: float = 168.0,
    bucket_hours: float = 24.0,
    store_id: str | None = None,
) -> CorrelationReport:
    """Compute pairwise Jaccard correlation across all 9
    autonomy domains."""
    from core.automation.autonomy_history import _DOMAIN_LOGS

    if bucket_hours <= 0:
        raise ValueError("bucket_hours must be > 0")
    if window_hours <= 0:
        raise ValueError("window_hours must be > 0")

    bucket_count = max(
        1, int((window_hours + bucket_hours - 1) // bucket_hours),
    )

    report = CorrelationReport(
        window_hours=window_hours,
        bucket_hours=bucket_hours,
        bucket_count=bucket_count,
        store_id=store_id,
    )

    # Step 1: per-domain bucket sets
    domain_buckets: dict[str, set[int]] = {}
    for short, pkg, log_modname, fn_name in _DOMAIN_LOGS:
        buckets = _domain_event_buckets(
            pkg, log_modname, fn_name,
            window_hours, bucket_hours, store_id,
        )
        domain_buckets[short] = buckets
        if buckets:
            report.active_domain_count += 1

    # Step 2: pairwise Jaccard
    domains = list(domain_buckets.keys())
    for i, a in enumerate(domains):
        for b in domains[i + 1:]:
            ba = domain_buckets[a]
            bb = domain_buckets[b]
            if not ba and not bb:
                # Skip pairs where both are zero (no signal)
                continue
            shared = len(ba & bb)
            union = len(ba | bb)
            jaccard = (
                shared / union if union > 0 else 0.0
            )
            report.pairs.append(CorrelationPair(
                domain_a=a,
                domain_b=b,
                buckets_a=len(ba),
                buckets_b=len(bb),
                shared=shared,
                union=union,
                jaccard=jaccard,
            ))

    # Sort by jaccard desc; tiebreak by shared desc
    report.pairs.sort(
        key=lambda p: (-p.jaccard, -p.shared),
    )

    return report
