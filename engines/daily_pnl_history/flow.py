"""Daily P&L History — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from . import store as store_mod

logger = logging.getLogger(__name__)


class DailyPnlHistoryEngine:
    ENGINE_NAME = "daily_pnl_history"

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

        action = str(data.get("action") or "summary").lower()

        if action == "record":
            return self._handle_record(data, start)
        if action == "query":
            return self._handle_query(data, start)
        if action == "trend":
            return self._handle_trend(data, start)
        if action == "summary":
            return self._handle_summary(data, start)
        return self._fail(
            f"unknown action {action!r}. Use record / "
            "query / trend / summary.",
            time.monotonic() - start,
        )

    # ── Handlers ──────────────────────────────────────

    def _handle_record(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        """Record snapshots for one store, or every store
        in the fleet."""
        store_filter = str(data.get("store_id") or "")
        try:
            window_days = int(data.get("window_days", 7))
        except (TypeError, ValueError):
            window_days = 7
        results: list[dict[str, Any]] = []
        store_count = 0
        wrote_count = 0
        try:
            from engines.store_pnl_tracker.tracker import (
                compute_store_pnl, compute_fleet_pnl,
            )
            if store_filter:
                store_ids = [store_filter]
            else:
                fr = compute_fleet_pnl(
                    days=window_days,
                )
                store_ids = [p.store_id for p in fr.by_store]
            for sid in store_ids:
                store_count += 1
                pnl = compute_store_pnl(
                    store_id=sid, days=window_days,
                )
                snapshot = asdict(pnl)
                wrote = store_mod.record_snapshot(snapshot)
                results.append({
                    "store_id": sid,
                    "wrote": wrote,
                    "verdict": pnl.verdict,
                    "gross_profit": pnl.gross_profit,
                })
                if wrote:
                    wrote_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "daily_pnl_history record raised: %s", exc,
            )

        return self._success(
            {
                "action": "record",
                "store_count": store_count,
                "wrote_count": wrote_count,
                "results": results,
                "snapshot_count_after":
                    store_mod.snapshot_count(),
                "next_action": (
                    f"Recorded {wrote_count}/{store_count} "
                    "snapshots."
                    if store_count > 0
                    else "No stores in fleet."
                ),
            },
            start,
        )

    def _handle_query(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        store_filter = str(data.get("store_id") or "")
        try:
            days = int(data.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        snaps = store_mod.query(
            store_id=store_filter, days=days,
        )
        return self._success(
            {
                "action": "query",
                "store_id": store_filter,
                "days": days,
                "count": len(snaps),
                "snapshots": list(snaps),
                "next_action": (
                    f"{len(snaps)} snapshot(s) returned."
                    if snaps
                    else "No snapshots match. Run with action=record first."
                ),
            },
            start,
        )

    def _handle_trend(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        store_filter = str(data.get("store_id") or "")
        try:
            days = int(data.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        if not store_filter:
            # Compute trend per store in history
            stores = store_mod.stores_with_history()
            trends = []
            for sid in stores:
                trends.append(
                    store_mod.compute_trend(
                        store_id=sid, days=days,
                    )
                )
            return self._success(
                {
                    "action": "trend",
                    "days": days,
                    "store_count": len(stores),
                    "trends": trends,
                    "next_action": (
                        f"{len(stores)} store(s) trend "
                        "computed."
                        if stores
                        else "No stores with history."
                    ),
                },
                start,
            )
        trend = store_mod.compute_trend(
            store_id=store_filter, days=days,
        )
        return self._success(
            {
                "action": "trend",
                "days": days,
                "trend": trend,
                "next_action": _trend_next_action(trend),
            },
            start,
        )

    def _handle_summary(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        total = store_mod.snapshot_count()
        stores = store_mod.stores_with_history()
        return self._success(
            {
                "action": "summary",
                "total_snapshots": total,
                "stores_with_history": stores,
                "store_count": len(stores),
                "next_action": (
                    f"{total} snapshots across "
                    f"{len(stores)} store(s). Run "
                    "shopai pnl-history --record to add."
                ),
            },
            start,
        )

    # ── Internal ──────────────────────────────────────

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


def _trend_next_action(trend: dict[str, Any]) -> str:
    verdict = trend.get("verdict", "no_data")
    if verdict == "no_data":
        return (
            "Need at least 4 snapshots for trend. Run "
            "shopai pnl-history --record daily."
        )
    if verdict == "rising":
        return (
            f"Profit rising +${trend.get('delta')} "
            f"({trend.get('slope_pct')}%). Reinvest."
        )
    if verdict == "falling":
        return (
            f"Profit falling ${trend.get('delta')} "
            f"({trend.get('slope_pct')}%). Investigate."
        )
    return (
        f"Flat: delta=${trend.get('delta')}. "
        "Try CRO or ad budget bump."
    )
