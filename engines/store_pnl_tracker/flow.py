"""Store P&L Tracker — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .tracker import compute_fleet_pnl, compute_store_pnl

logger = logging.getLogger(__name__)


class StorePnlTrackerEngine:
    ENGINE_NAME = "store_pnl_tracker"

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
        days = max(1, min(days, 365))
        store_id = str(data.get("store_id") or "")

        if store_id:
            pnl = compute_store_pnl(
                store_id=store_id, days=days,
            )
            return self._success(
                {
                    "mode": "single",
                    "store_id": store_id,
                    "days": days,
                    "pnl": asdict(pnl),
                    "next_action": _single_next_action(pnl),
                },
                start,
            )

        report = compute_fleet_pnl(days=days)
        return self._success(
            {
                "mode": "fleet",
                "days": days,
                "fleet_revenue": report.fleet_revenue,
                "fleet_refunds": report.fleet_refunds,
                "fleet_ad_spend": report.fleet_ad_spend,
                "fleet_esp_spend": report.fleet_esp_spend,
                "fleet_shipping_cost":
                    report.fleet_shipping_cost,
                "fleet_gross_profit":
                    report.fleet_gross_profit,
                "fleet_margin_pct": report.fleet_margin_pct,
                "by_store": [
                    asdict(p) for p in report.by_store
                ],
                "store_count": len(report.by_store),
                "next_action": _fleet_next_action(report),
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


def _single_next_action(pnl: Any) -> str:
    verdict = getattr(pnl, "verdict", "no_data")
    if verdict == "no_data":
        return (
            f"No revenue or cost in {pnl.days}d window. Try "
            "wider window or earn-bootstrap."
        )
    if verdict == "profitable":
        return (
            f"Profitable: gross_profit=${pnl.gross_profit:.2f} "
            f"({pnl.margin_pct:.1f}% margin). Reinvest: "
            "shopai ads launch --budget-daily bumped."
        )
    if verdict == "loss":
        # W963-94: render -$X (sign before $) when profit < 0
        sign = "-" if pnl.gross_profit < 0 else ""
        return (
            f"Loss: gross_profit="
            f"{sign}${abs(pnl.gross_profit):.2f}. "
            "Check ad spend vs revenue. shopai roas to drill."
        )
    return (
        f"Break-even ({pnl.gross_profit:.2f}). Optimize: "
        "shopai cro variants."
    )


def _fleet_next_action(report) -> str:
    n = len(report.by_store)
    if n == 0:
        return "No stores in fleet."
    if report.fleet_gross_profit > 0:
        return (
            f"Fleet profitable: ${report.fleet_gross_profit:.2f} "
            f"({report.fleet_margin_pct:.1f}% margin)"
        )
    if report.fleet_gross_profit < 0:
        # W963-94: render -$X (sign before $) when profit < 0
        return (
            f"Fleet loss: "
            f"-${abs(report.fleet_gross_profit):.2f}. "
            "Identify the losing stores."
        )
    return "Fleet at break-even."
