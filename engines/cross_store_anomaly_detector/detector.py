"""Compute fleet norms + flag outliers.

Robust statistics: median + MAD (median absolute deviation),
not mean+stddev — single rogue store can't skew the norm.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StoreMetrics:
    store_id: str
    revenue_7d: float = 0.0
    earning_engine_count: int = 0
    funnel_drop_rate: float = 0.0
    approval_pending: int = 0
    checkup_partial_count: int = 0


@dataclass
class AnomalyAlert:
    store_id: str
    metric: str
    value: float
    fleet_median: float
    fleet_mad: float
    deviation_mads: float
    direction: str  # high / low


@dataclass
class AnomalyReport:
    metric_filter: str = ""
    mad_threshold: float = 3.0
    total_stores: int = 0
    fleet_norms: dict[str, dict[str, float]] = field(
        default_factory=dict,
    )
    alerts: list[AnomalyAlert] = field(default_factory=list)
    skipped_metrics: list[str] = field(default_factory=list)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    n = len(sv)
    mid = n // 2
    if n % 2 == 0:
        return (sv[mid - 1] + sv[mid]) / 2.0
    return sv[mid]


def _mad(values: list[float]) -> tuple[float, float]:
    """Return (median, robust-deviation).

    Primary: median absolute deviation (MAD). Robust to
    outliers.

    Fallback: when MAD is exactly 0 (most fleet values are
    identical, e.g. 4 stores at 100 + 1 at 1000), the median
    deviation collapses to 0 and no outlier can ever exceed
    a threshold. In that case we fall back to mean absolute
    deviation, which IS sensitive to the outlier."""
    if not values:
        return (0.0, 0.0)
    med = _median(values)
    deviations = [abs(v - med) for v in values]
    m = _median(deviations)
    if m == 0.0 and deviations:
        # Mean absolute deviation fallback
        non_zero = [d for d in deviations if d > 0]
        if non_zero:
            m = sum(deviations) / len(deviations)
    return (med, m)


def _store_metrics(store_id: str) -> StoreMetrics | None:
    m = StoreMetrics(store_id=store_id)
    try:
        # Revenue
        from engines.earnings_by_engine import (
            EarningsByEngineEngine,
        )
        er = EarningsByEngineEngine().run({
            "data": {
                "window_hours": 168.0, "store_id": store_id,
            },
        })
        edata = er.get("data") or {}
        m.revenue_7d = float(
            edata.get("total_attributed_revenue") or 0.0,
        )
        m.earning_engine_count = int(
            edata.get("earning_count") or 0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly: revenue lookup raised for %s: %s",
            store_id, exc,
        )

    try:
        # Funnel
        from engines.conversion_funnel import (
            ConversionFunnelEngine,
        )
        fr = ConversionFunnelEngine().run({
            "data": {"days": 7, "store_id": store_id},
        })
        fdata = fr.get("data") or {}
        m.funnel_drop_rate = float(
            fdata.get("weakest_drop") or 0.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly: funnel lookup raised for %s: %s",
            store_id, exc,
        )

    try:
        # Approval queue depth
        from core.approval.queue import get_approval_queue
        pending = list(
            get_approval_queue().list_pending(
                store_id=store_id, limit=500,
            )
        )
        m.approval_pending = len(pending)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly: queue lookup raised for %s: %s",
            store_id, exc,
        )

    try:
        # Checkup partial count
        from engines.checkup import CheckupEngine
        cr = CheckupEngine().run({
            "data": {"store_id": store_id},
        })
        cdata = cr.get("data") or {}
        m.checkup_partial_count = int(
            (cdata.get("counts") or {}).get("partial", 0)
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly: checkup lookup raised for %s: %s",
            store_id, exc,
        )

    return m


_METRIC_GETTERS = {
    "revenue_7d": lambda m: m.revenue_7d,
    "earning_engine_count": (
        lambda m: float(m.earning_engine_count)
    ),
    "funnel_drop_rate": lambda m: m.funnel_drop_rate,
    "approval_pending": lambda m: float(m.approval_pending),
    "checkup_partial_count": (
        lambda m: float(m.checkup_partial_count)
    ),
}


def _list_fleet_stores() -> list[str]:
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        out: list[str] = []
        for s in (sm.list_stores() or []):
            if not isinstance(s, dict):
                continue
            sid = s.get("store_id")
            if sid and sid not in out:
                out.append(sid)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "anomaly: store listing raised: %s", exc,
        )
        return []


def detect_anomalies(
    *,
    metric_filter: str = "",
    mad_threshold: float = 3.0,
    metrics: list[StoreMetrics] | None = None,
) -> AnomalyReport:
    """Compute per-metric fleet norms + flag outliers."""
    report = AnomalyReport(
        metric_filter=metric_filter,
        mad_threshold=max(0.5, mad_threshold),
    )

    if metrics is None:
        store_ids = _list_fleet_stores()
        metrics_list = []
        for sid in store_ids:
            m = _store_metrics(sid)
            if m:
                metrics_list.append(m)
        metrics = metrics_list

    report.total_stores = len(metrics)
    if report.total_stores < 3:
        # Need at least 3 stores to compute meaningful norm
        report.skipped_metrics = list(_METRIC_GETTERS.keys())
        return report

    keys = (
        [metric_filter]
        if metric_filter else list(_METRIC_GETTERS.keys())
    )

    for key in keys:
        getter = _METRIC_GETTERS.get(key)
        if getter is None:
            report.skipped_metrics.append(key)
            continue
        values = [getter(m) for m in metrics]
        med, mad = _mad(values)
        report.fleet_norms[key] = {
            "median": round(med, 3),
            "mad": round(mad, 3),
        }
        if mad == 0.0:
            # No variation across the fleet — nothing to flag.
            continue
        for m in metrics:
            v = getter(m)
            deviation = abs(v - med) / mad
            if deviation >= report.mad_threshold:
                direction = "high" if v > med else "low"
                report.alerts.append(AnomalyAlert(
                    store_id=m.store_id,
                    metric=key,
                    value=round(v, 3),
                    fleet_median=round(med, 3),
                    fleet_mad=round(mad, 3),
                    deviation_mads=round(deviation, 2),
                    direction=direction,
                ))

    report.alerts.sort(
        key=lambda a: a.deviation_mads, reverse=True,
    )
    return report


def available_metrics() -> list[str]:
    return list(_METRIC_GETTERS.keys())
