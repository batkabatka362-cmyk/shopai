"""AGI Earnings History — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from . import store as store_mod

logger = logging.getLogger(__name__)


class AgiEarningsHistoryEngine:
    ENGINE_NAME = "agi_earnings_history"

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

        action = str(
            data.get("action") or "summary",
        ).lower()

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

    def _handle_record(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        try:
            days = int(data.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        try:
            window_h = float(
                data.get(
                    "attribution_window_hours", 48.0,
                ),
            )
        except (TypeError, ValueError):
            window_h = 48.0
        try:
            from engines.agi_earnings_summary.summarizer import (
                compute_summary,
            )
            s = compute_summary(
                days=days,
                attribution_window_hours=window_h,
            )
            snapshot = {
                "ts": time.time(),
                "days": s.days,
                "verdict": s.verdict,
                "gross_profit": s.fleet_gross_profit,
                "attribution_pct": s.fleet_attribution_pct,
                "monthly_run_rate": s.monthly_run_rate,
                "trend_verdict": s.trend_verdict,
                "attributed_revenue": (
                    s.fleet_attributed_revenue
                ),
                "organic_revenue": s.fleet_organic_revenue,
                "store_count": s.store_count,
                "profitable_store_count": (
                    s.profitable_store_count
                ),
                "loss_store_count": s.loss_store_count,
            }
            wrote = store_mod.record_snapshot(snapshot)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "earnings_history record raised: %s", exc,
            )
            wrote = False
            snapshot = {}

        return self._success(
            {
                "action": "record",
                "wrote": wrote,
                "snapshot": snapshot,
                "snapshot_count_after":
                    store_mod.snapshot_count(),
                "next_action": (
                    f"Recorded verdict="
                    f"{snapshot.get('verdict', '?')}, "
                    f"profit=$"
                    f"{snapshot.get('gross_profit', 0):.0f}"
                    if wrote else
                    "Snapshot NOT recorded (test env or "
                    "write failure)."
                ),
            },
            start,
        )

    def _handle_query(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        try:
            days = int(data.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        try:
            limit = int(data.get("limit", 100))
        except (TypeError, ValueError):
            limit = 100
        days = max(1, min(days, 365))
        limit = max(1, min(limit, 5000))
        snaps = store_mod.query(days=days, limit=limit)
        return self._success(
            {
                "action": "query",
                "days": days,
                "limit": limit,
                "count": len(snaps),
                "snapshots": snaps,
                "next_action": (
                    f"{len(snaps)} snapshot(s) in last "
                    f"{days}d."
                ),
            },
            start,
        )

    def _handle_trend(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        try:
            days = int(data.get("days", 14))
        except (TypeError, ValueError):
            days = 14
        days = max(2, min(days, 365))
        trend = store_mod.compute_trend(days=days)
        return self._success(
            {
                "action": "trend",
                "trend": trend,
                "next_action": _trend_next(trend),
            },
            start,
        )

    def _handle_summary(
        self, data: dict[str, Any], start: float,
    ) -> dict[str, Any]:
        latest = store_mod.latest()
        total = store_mod.snapshot_count()
        return self._success(
            {
                "action": "summary",
                "total_snapshots": total,
                "latest": latest,
                "next_action": (
                    f"{total} snapshots logged. Run "
                    "shopai earnings-history --record "
                    "daily (via cron)."
                ),
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


def _trend_next(trend: dict[str, Any]) -> str:
    v = trend.get("verdict", "no_data")
    n = trend.get("sample_count", 0)
    if v == "no_data":
        return (
            f"Need at least 2 snapshots ({n} present). "
            "Run shopai earnings-history --record daily."
        )
    if v == "improving":
        return (
            f"AGI earnings IMPROVING over "
            f"{trend.get('days')}d "
            f"(rank delta=+{trend.get('delta')}). Keep "
            "going."
        )
    if v == "declining":
        return (
            f"AGI earnings DECLINING over "
            f"{trend.get('days')}d "
            f"(rank delta={trend.get('delta')}). Check "
            "shopai engine alerts."
        )
    return (
        f"AGI earnings FLAT over {trend.get('days')}d "
        f"({n} samples). Consider "
        "shopai approvals digest."
    )
