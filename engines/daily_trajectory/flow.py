"""Daily Trajectory Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .analyzer import (
    TrajectoryReport,
    analyze_trajectory,
    render_sparkline,
)

logger = logging.getLogger(__name__)


class DailyTrajectoryEngine:
    ENGINE_NAME = "daily_trajectory"

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
            days = int(data.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        store_id = data.get("store_id")

        report = analyze_trajectory(
            days=days,
            store_id=store_id,
            orders=data.get("orders"),
        )

        return self._success(
            {
                "days": report.days,
                "store_id": report.store_id,
                "verdict": report.verdict,
                "slope_pct": report.slope_pct,
                "total_orders": report.total_orders,
                "total_revenue": report.total_revenue,
                "avg_daily_revenue": report.avg_daily_revenue,
                "buckets": [
                    asdict(b) for b in report.buckets
                ],
                "sparkline": render_sparkline(report.buckets),
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


def _next_action(report: TrajectoryReport) -> str:
    if report.verdict == "cold_start":
        if report.total_orders == 0:
            return (
                "0 orders in window. Run: shopai earn-bootstrap "
                "+ shopai cycle run --yes to seed traffic."
            )
        return (
            f"{report.total_orders} order(s), early data. "
            "Need more days to compute slope."
        )
    if report.verdict == "rising":
        return (
            f"Rising +{report.slope_pct:.1f}% per half-window. "
            "Reinvest winners: shopai roas + shopai ads launch."
        )
    if report.verdict == "declining":
        return (
            f"Declining {report.slope_pct:.1f}%. Check: "
            "shopai engine alerts + shopai checkup."
        )
    return (
        f"Flat ({report.slope_pct:+.1f}%). Try: shopai cro "
        "variants or shopai discount_strategy."
    )
