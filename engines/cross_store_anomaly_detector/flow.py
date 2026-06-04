"""Cross-Store Anomaly Detector — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .detector import (
    AnomalyReport,
    available_metrics,
    detect_anomalies,
)

logger = logging.getLogger(__name__)


class CrossStoreAnomalyDetectorEngine:
    ENGINE_NAME = "cross_store_anomaly_detector"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        payload = self._safe_copy(input_payload)
        if payload is None:
            return self._fail("Input copy failed", 0.0)
        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)
        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        metric_filter = str(data.get("metric") or "")
        try:
            mad_threshold = float(
                data.get("mad_threshold", 3.0),
            )
        except (TypeError, ValueError):
            mad_threshold = 3.0

        report = detect_anomalies(
            metric_filter=metric_filter,
            mad_threshold=mad_threshold,
            metrics=data.get("metrics"),
        )

        return self._success(
            {
                "metric_filter": report.metric_filter,
                "mad_threshold": report.mad_threshold,
                "total_stores": report.total_stores,
                "fleet_norms": report.fleet_norms,
                "alert_count": len(report.alerts),
                "alerts": [asdict(a) for a in report.alerts],
                "skipped_metrics": report.skipped_metrics,
                "available_metrics": available_metrics(),
                "next_action": _next_action(report),
            },
            start,
        )

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    def _success(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": data,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(
                    time.monotonic() - start, 3,
                ),
            },
            "error": None,
        }

    def _fail(
        self, reason: str, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }


def _next_action(report: AnomalyReport) -> str:
    if report.total_stores < 3:
        return (
            "Fleet too small for meaningful norms "
            f"({report.total_stores} stores; need >=3)."
        )
    if not report.alerts:
        return (
            f"No outliers at {report.mad_threshold:.1f} MAD "
            "threshold. Try --mad 2.0 for tighter detection."
        )
    top = report.alerts[0]
    return (
        f"Top outlier: store {top.store_id} on "
        f"{top.metric} ({top.deviation_mads:.1f} MADs "
        f"{top.direction}). Drill: shopai strategist "
        f"--store {top.store_id}"
    )
