"""Verdict-flip thrash detection (W904).

Builds on the W900 history layer. A "flip" is a verdict
transition between two adjacent snapshots (e.g. armed ->
degraded -> armed). Operators wanted a signal when the
autonomous merchant thrashes — say 5+ flips in 1 hour
suggests a degradation root-cause that the alerter doesn't
catch (alerts only fire on the snapshot, not the rate of
change).

This module reads the W900 history (no writes) and emits a
ThrashReport with per-bucket flip counts + a verdict
("calm" / "elevated" / "thrashing").
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


_ELEVATED_THRESHOLD = 3
_THRASHING_THRESHOLD = 5


@dataclass
class ThrashBucket:
    start_at: float
    end_at: float
    flip_count: int
    verdict_sequence: list[str] = field(default_factory=list)

    @property
    def density_label(self) -> str:
        if self.flip_count >= _THRASHING_THRESHOLD:
            return "thrashing"
        if self.flip_count >= _ELEVATED_THRESHOLD:
            return "elevated"
        return "calm"


@dataclass
class ThrashReport:
    store_id: str | None = None
    window_hours: float = 24.0
    bucket_hours: float = 1.0
    captured_at: float = field(default_factory=time.time)
    buckets: list[ThrashBucket] = field(default_factory=list)

    @property
    def total_flips(self) -> int:
        return sum(b.flip_count for b in self.buckets)

    @property
    def peak_flips(self) -> int:
        if not self.buckets:
            return 0
        return max(b.flip_count for b in self.buckets)

    @property
    def verdict(self) -> str:
        if self.peak_flips >= _THRASHING_THRESHOLD:
            return "thrashing"
        if self.peak_flips >= _ELEVATED_THRESHOLD:
            return "elevated"
        return "calm"


def compute_thrash(
    *,
    window_hours: float = 24.0,
    bucket_hours: float = 1.0,
    store_id: str | None = None,
) -> ThrashReport:
    """Compute the flip-density report from W900 history.

    Wave 937 bugfix: when ``store_id`` is None (fleet-wide
    call), each store's history is walked independently so
    cross-store transitions don't manufacture fake flips.
    Wave 937 bugfix: ``math.ceil`` for n_buckets so the tail
    of the window isn't silently dropped.
    Wave 937 bugfix: sample ``now`` ONCE at the top so the
    bucket boundaries match the history-read window.
    """
    import math

    now = time.time()
    bucket_h = max(bucket_hours, 0.1)
    report = ThrashReport(
        store_id=store_id,
        window_hours=window_hours,
        bucket_hours=bucket_h,
        captured_at=now,
    )
    try:
        from core.automation.autonomy_overview_history import (
            recent_entries,
        )
        entries = recent_entries(
            limit=10_000,
            store_id=store_id,
            window_hours=window_hours,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("thrash history read raised: %s", exc)
        return report

    if not entries:
        return report

    bucket_seconds = bucket_h * 3600.0
    n_buckets = int(math.ceil(
        max(1.0, (window_hours * 3600.0) / bucket_seconds),
    ))

    buckets: list[ThrashBucket] = []
    for i in range(n_buckets):
        start = now - (n_buckets - i) * bucket_seconds
        end = start + bucket_seconds
        buckets.append(ThrashBucket(
            start_at=start, end_at=end, flip_count=0,
        ))

    # Group by store_id so fleet-wide calls don't manufacture
    # flips at store boundaries. Per-store calls (store_id set)
    # collapse to a single group.
    groups: dict[str | None, list] = {}
    for entry in entries:
        groups.setdefault(entry.store_id, []).append(entry)

    for entries_for_store in groups.values():
        chrono = sorted(
            entries_for_store, key=lambda e: e.captured_at,
        )
        prev_verdict: str | None = None
        for entry in chrono:
            ts = entry.captured_at
            bucket_idx = None
            for i, b in enumerate(buckets):
                if b.start_at <= ts < b.end_at:
                    bucket_idx = i
                    break
            if bucket_idx is None:
                continue
            b = buckets[bucket_idx]
            b.verdict_sequence.append(entry.verdict)
            if (
                prev_verdict is not None
                and entry.verdict != prev_verdict
            ):
                b.flip_count += 1
            prev_verdict = entry.verdict

    report.buckets = buckets
    return report


def latest_thrash_verdict(
    *,
    store_id: str | None = None,
    window_hours: float = 24.0,
) -> str:
    """Convenience: just the top-level verdict."""
    return compute_thrash(
        window_hours=window_hours, store_id=store_id,
    ).verdict
