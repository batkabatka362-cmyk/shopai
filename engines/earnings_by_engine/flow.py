"""Earnings By Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .analyzer import analyze_earnings_by_engine

logger = logging.getLogger(__name__)


class EarningsByEngineEngine:
    ENGINE_NAME = "earnings_by_engine"

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

        try:
            window_hours = float(
                data.get("window_hours", 168.0),
            )
        except (TypeError, ValueError):
            window_hours = 168.0
        store_id = data.get("store_id")

        report = analyze_earnings_by_engine(
            window_hours=window_hours,
            store_id=store_id,
            orders=data.get("orders"),
        )

        return self._success(
            {
                "window_hours": report.window_hours,
                "store_id": report.store_id,
                "total_attributed_orders":
                    report.total_attributed_orders,
                "total_attributed_revenue":
                    report.total_attributed_revenue,
                "earning_count": report.earning_count,
                "no_data_count": report.no_data_count,
                "engines": [asdict(e) for e in report.engines],
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


def _next_action(report) -> str:
    if report.total_attributed_orders == 0:
        return (
            "0 attributable orders. Wait for revenue or "
            "extend window: --window-hours 720 (30d)."
        )
    if report.earning_count == 0:
        return (
            f"{report.total_attributed_orders} order(s) "
            "attributed, none cross $10 threshold. Run "
            "shopai cycle run --yes to fire more engines."
        )
    return (
        f"{report.earning_count} engine(s) earning. "
        "Reinvest: shopai roas + shopai ads launch "
        "--budget-daily on top channel."
    )
