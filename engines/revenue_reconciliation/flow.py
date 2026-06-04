"""Revenue Reconciliation — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .reconciler import (
    FleetRecon,
    reconcile_fleet,
    reconcile_store,
)

logger = logging.getLogger(__name__)


class RevenueReconciliationEngine:
    ENGINE_NAME = "revenue_reconciliation"

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
            days = int(data.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        try:
            window_h = float(
                data.get("attribution_window_hours", 48.0),
            )
        except (TypeError, ValueError):
            window_h = 48.0
        store_id = str(data.get("store_id") or "")

        if store_id:
            rc = reconcile_store(
                store_id=store_id, days=days,
                attribution_window_hours=window_h,
            )
            return self._success(
                {
                    "mode": "single",
                    "store_id": store_id,
                    "days": days,
                    "attribution_window_hours": window_h,
                    "recon": asdict(rc),
                    "next_action": _single_next(rc),
                },
                start,
            )

        report = reconcile_fleet(
            days=days,
            attribution_window_hours=window_h,
        )
        return self._success(
            {
                "mode": "fleet",
                "days": days,
                "attribution_window_hours": window_h,
                "fleet_attributed_revenue":
                    report.fleet_attributed_revenue,
                "fleet_organic_revenue":
                    report.fleet_organic_revenue,
                "fleet_attribution_pct":
                    report.fleet_attribution_pct,
                "fleet_orphan_action_count":
                    report.fleet_orphan_action_count,
                "store_count": len(report.by_store),
                "by_store": [
                    asdict(r) for r in report.by_store
                ],
                "next_action": _fleet_next(report),
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


def _single_next(rc) -> str:
    if rc.order_count == 0:
        return (
            f"No orders in {rc.days}d for {rc.store_id}. "
            "Wait or earn-bootstrap."
        )
    if rc.attributed_order_count == 0:
        return (
            f"All {rc.order_count} order(s) are ORGANIC. "
            "AGI not driving revenue here yet."
        )
    pct = (
        rc.attributed_order_count / rc.order_count * 100.0
        if rc.order_count else 0.0
    )
    return (
        f"{rc.attributed_order_count}/"
        f"{rc.order_count} orders attributed to AGI "
        f"({pct:.0f}%). orphans={rc.orphan_action_count}"
    )


def _fleet_next(report: FleetRecon) -> str:
    n = len(report.by_store)
    if n == 0:
        return "No stores in fleet."
    total = (
        report.fleet_attributed_revenue
        + report.fleet_organic_revenue
    )
    if total == 0:
        return (
            f"No revenue across {n} store(s). "
            "Run shopai cycle run --yes."
        )
    return (
        f"Fleet attribution: "
        f"${report.fleet_attributed_revenue:.2f} AGI / "
        f"${report.fleet_organic_revenue:.2f} organic "
        f"({report.fleet_attribution_pct:.0f}% AGI). "
        f"orphans={report.fleet_orphan_action_count}"
    )
