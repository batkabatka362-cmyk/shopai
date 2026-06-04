"""Compute per-engine calibrated thresholds from outcome
history."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_BAND_THRESHOLDS = {
    "relaxed":  0.6,
    "standard": 0.8,
    "cautious": 0.9,
    "blocked":  1.1,    # never auto-trust
    "unknown":  0.8,    # falls back to standard
}


@dataclass
class EngineCalibration:
    engine: str
    store_id: str = ""
    sample_size: int = 0
    positive_ratio: float = 0.0
    band: str = "unknown"  # relaxed / standard / cautious / blocked / unknown
    calibrated_threshold: float = 0.8


@dataclass
class CalibrationReport:
    store_id: str
    min_sample: int
    total_engines: int = 0
    calibrations: list[EngineCalibration] = field(
        default_factory=list,
    )
    band_counts: dict[str, int] = field(default_factory=dict)


def _band_for(
    sample: int,
    positive_ratio: float,
    *,
    min_sample: int,
) -> str:
    if sample < min_sample:
        return "unknown"
    if positive_ratio >= 0.95:
        return "relaxed"
    if positive_ratio >= 0.80:
        return "standard"
    if positive_ratio >= 0.60:
        return "cautious"
    return "blocked"


def _list_engines() -> list[str]:
    """Best-effort: pull distinct engine names from recent
    executed actions in the queue."""
    try:
        from core.approval.queue import (
            get_approval_queue, ApprovalStatus,
        )
        q = get_approval_queue()
        out: list[str] = []
        for action in q.list_by_status(
            ApprovalStatus.EXECUTED, limit=500,
        ) or []:
            e = getattr(action, "engine", None)
            if e and e not in out:
                out.append(e)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "calibrator: engine listing raised: %s", exc,
        )
        return []


def _engine_outcome_stats(
    engine: str, store_id: str | None,
) -> tuple[int, int]:
    """Return (positive, negative) outcome counts."""
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        stats = q.engine_outcome_stats(
            engine, store_id=store_id,
        ) or {}
        return (
            int(stats.get("positive_count", 0) or 0),
            int(stats.get("negative_count", 0) or 0),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "calibrator: stats lookup raised: %s", exc,
        )
        return (0, 0)


def calibrate(
    *,
    store_id: str | None = None,
    min_sample: int = 5,
    engines: list[str] | None = None,
) -> CalibrationReport:
    """Compute calibrated thresholds for each engine."""
    report = CalibrationReport(
        store_id=store_id or "",
        min_sample=max(1, min_sample),
    )
    eng_list = (
        engines if engines is not None else _list_engines()
    )
    report.total_engines = len(eng_list)

    for engine in eng_list:
        pos, neg = _engine_outcome_stats(engine, store_id)
        sample = pos + neg
        ratio = pos / sample if sample > 0 else 0.0
        band = _band_for(
            sample, ratio, min_sample=report.min_sample,
        )
        cal = EngineCalibration(
            engine=engine,
            store_id=store_id or "",
            sample_size=sample,
            positive_ratio=round(ratio, 3),
            band=band,
            calibrated_threshold=_BAND_THRESHOLDS[band],
        )
        report.calibrations.append(cal)

    # Sort by band severity (blocked first, then by ratio asc)
    band_order = {
        "blocked": 0, "cautious": 1, "unknown": 2,
        "standard": 3, "relaxed": 4,
    }
    report.calibrations.sort(
        key=lambda c: (
            band_order.get(c.band, 99),
            c.positive_ratio,
        )
    )
    # Tally bands
    for c in report.calibrations:
        report.band_counts[c.band] = (
            report.band_counts.get(c.band, 0) + 1
        )
    return report


def band_thresholds() -> dict[str, float]:
    return dict(_BAND_THRESHOLDS)
