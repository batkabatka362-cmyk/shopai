"""PerStorePnLEngine -- Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .snapshot import (
    compute_fleet_snapshot,
    compute_snapshot,
)

logger = logging.getLogger(__name__)


class PerStorePnLEngine:
    ENGINE_NAME = "per_store_pnl"

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
        store_id = str(data.get("store_id") or "")

        try:
            if store_id:
                snap = compute_snapshot(
                    store_id,
                    window_hours=window_hours,
                )
                out = {
                    "view": "single",
                    "store_id": store_id,
                    "window_hours": window_hours,
                    "snapshot": self._serialise(snap),
                }
            else:
                snaps = compute_fleet_snapshot(
                    window_hours=window_hours,
                )
                out = {
                    "view": "fleet",
                    "window_hours": window_hours,
                    "store_count": len(snaps),
                    "losing_count": sum(
                        1 for s in snaps
                        if s.state.value == "losing"
                    ),
                    "thriving_count": sum(
                        1 for s in snaps
                        if s.state.value == "thriving"
                    ),
                    "snapshots": [
                        self._serialise(s) for s in snaps
                    ],
                    "fleet_totals": self._fleet_totals(snaps),
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "per_store_pnl query raised: %s", exc,
            )
            return self._fail(
                f"query raised: {exc}", 0.0,
            )

        return self._success(out, start)

    @staticmethod
    def _fleet_totals(
        snaps: list[Any],
    ) -> dict[str, Any]:
        if not snaps:
            return {
                "total_spend_usd": 0.0,
                "total_revenue_usd": 0.0,
                "total_profit_usd": 0.0,
                "fleet_margin_pct": 0.0,
                "fleet_roas_ratio": 0.0,
            }
        spend = sum(s.spend_usd for s in snaps)
        revenue = sum(s.revenue_usd for s in snaps)
        profit = revenue - spend
        margin = (
            profit / revenue * 100.0 if revenue > 0 else 0.0
        )
        roas = (
            revenue / spend if spend > 0
            else (9999.0 if revenue > 0 else 0.0)
        )
        return {
            "total_spend_usd": round(spend, 4),
            "total_revenue_usd": round(revenue, 2),
            "total_profit_usd": round(profit, 2),
            "fleet_margin_pct": round(margin, 1),
            "fleet_roas_ratio": round(roas, 2),
        }

    @staticmethod
    def _serialise(s: Any) -> dict[str, Any]:
        return {
            "store_id": s.store_id,
            "window_hours": s.window_hours,
            "spend_usd": s.spend_usd,
            "revenue_usd": s.revenue_usd,
            "attributed_revenue_usd": s.attributed_revenue_usd,
            "profit_usd": s.profit_usd,
            "margin_pct": s.margin_pct,
            "roas_ratio": s.roas_ratio,
            "state": s.state.value,
            "has_cost_data": s.has_cost_data,
            "has_revenue_data": s.has_revenue_data,
            "notes": list(s.notes),
        }

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
