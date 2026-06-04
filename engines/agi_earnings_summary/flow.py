"""AGI Earnings Summary — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .summarizer import EarningsSummary, compute_summary

logger = logging.getLogger(__name__)


class AgiEarningsSummaryEngine:
    ENGINE_NAME = "agi_earnings_summary"

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
        try:
            trend_days = int(data.get("trend_days", 30))
        except (TypeError, ValueError):
            trend_days = 30

        s = compute_summary(
            days=days,
            attribution_window_hours=window_h,
            trend_days=trend_days,
        )
        out = asdict(s)
        out["next_action"] = _next_action(s)
        return self._success(out, start)

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


def _next_action(s: EarningsSummary) -> str:
    if s.verdict == "no_data":
        return (
            f"No revenue across {s.store_count} store(s) "
            f"in {s.days}d. Run shopai cycle run --yes "
            "or shopai earn-bootstrap."
        )
    if s.verdict == "organic_only":
        return (
            f"${s.fleet_organic_revenue:.0f} organic / 0 "
            "AGI. Wire revenue-driving engines: shopai "
            "engine ranking --sort outcome_score."
        )
    if s.verdict == "attributed_loss":
        return (
            f"AGI attributing ${s.fleet_attributed_revenue:.0f} "
            f"BUT fleet loss "
            f"(${s.fleet_gross_profit:.0f}). Cut ad spend: "
            "shopai roas to find culprits."
        )
    # earning
    return (
        f"AGI earning: ${s.fleet_gross_profit:.0f} profit / "
        f"{s.fleet_attribution_pct:.0f}% attributed. "
        f"Monthly run-rate ${s.monthly_run_rate:.0f}. "
        f"Trend: {s.trend_verdict}."
    )
