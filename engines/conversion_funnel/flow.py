"""Conversion Funnel Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .analyzer import analyze_funnel

logger = logging.getLogger(__name__)


class ConversionFunnelEngine:
    ENGINE_NAME = "conversion_funnel"

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

        store_id = data.get("store_id")
        sessions = data.get("sessions")
        cart_adds = data.get("cart_adds")
        orders_arg = data.get("orders")
        abandoned_arg = data.get("abandoned")

        report = analyze_funnel(
            days=days,
            store_id=store_id,
            orders=orders_arg,
            abandoned=abandoned_arg,
            sessions=(
                int(sessions)
                if isinstance(sessions, (int, float))
                else None
            ),
            cart_adds=(
                int(cart_adds)
                if isinstance(cart_adds, (int, float))
                else None
            ),
        )

        return self._success(
            {
                "days": report.days,
                "store_id": report.store_id,
                "verdict": report.verdict,
                "weakest_link": report.weakest_link,
                "weakest_drop": round(
                    report.weakest_drop, 3,
                ),
                "stages": [
                    asdict(s) for s in report.stages
                ],
                "next_action": report.next_action,
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
