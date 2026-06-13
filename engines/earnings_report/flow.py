"""Earnings Report — flow orchestrator.

Pattern Q canonical envelope. Hydrates recent orders via the
shared hydrator (SHOPIFY_FETCH_ORDERS), aggregates by window
side, and returns the operator-facing earnings shape.

``input_payload.data``:
    window_hours (float, default 24)
    store_id (str | None)
    orders (list, optional — bypasses hydration for tests)
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines._shopify_hydrator import hydrate

from .analyzer import EarningsReport, analyze, to_dict

logger = logging.getLogger(__name__)


_DEFAULT_WINDOW_HOURS = 24.0
_HYDRATE_LIMIT = 250
# Cap to defend against malicious / huge windows.
_MAX_WINDOW_HOURS = 24.0 * 90.0


class EarningsReportEngine:
    """Read recent orders, compute net revenue + delta."""

    ENGINE_NAME = "earnings_report"

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

        # Window resolution.
        try:
            window_hours = float(
                data.get("window_hours", _DEFAULT_WINDOW_HOURS),
            )
        except (TypeError, ValueError):
            return self._fail(
                "window_hours must be numeric",
                time.monotonic() - start,
            )
        if window_hours <= 0:
            return self._fail(
                "window_hours must be > 0",
                time.monotonic() - start,
            )
        window_hours = min(window_hours, _MAX_WINDOW_HOURS)

        store_id_raw = data.get("store_id")
        store_id = str(store_id_raw) if store_id_raw else None

        # Order resolution. Caller can pass orders directly for
        # tests / off-platform analysis; otherwise hydrate from
        # Shopify via SHOPIFY_FETCH_ORDERS.
        orders = data.get("orders")
        if not isinstance(orders, list):
            # The hydrator pulls a fixed-size page; that's fine
            # for the common 24-72h window. Operators wanting a
            # 30-day window may need to paginate (Phase 2).
            orders = hydrate(
                supplied=[],
                capability_name="SHOPIFY_FETCH_ORDERS",
                list_field="orders",
                limit=_HYDRATE_LIMIT,
            )
            if not isinstance(orders, list):
                orders = []

        report = analyze(
            orders=orders,
            window_hours=window_hours,
            store_id=store_id,
        )
        elapsed = time.monotonic() - start
        return self._success(report, elapsed)

    # ── Internal ──────────────────────────────────────────

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
        self, report: EarningsReport, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": to_dict(report),
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
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
