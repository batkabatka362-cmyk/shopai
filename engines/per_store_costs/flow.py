"""PerStoreCostsEngine -- Pattern Q envelope around the
cost query API."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .query import (
    costs_by_adapter,
    costs_by_store,
    costs_total,
    get_recent_events,
)

logger = logging.getLogger(__name__)


class PerStoreCostsEngine:
    ENGINE_NAME = "per_store_costs"

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
        view = str(data.get("view") or "summary").lower()
        include_archive = bool(
            data.get("include_archive", False),
        )

        try:
            if view == "by_store":
                raw = costs_by_store(
                    window_hours=window_hours,
                    include_archive=include_archive,
                )
                out = {
                    "view": "by_store",
                    "window_hours": window_hours,
                    "stores": [
                        self._serialise_store_summary(s)
                        for s in raw.values()
                    ],
                }
            elif view == "by_adapter":
                raw = costs_by_adapter(
                    store_id=store_id,
                    window_hours=window_hours,
                    include_archive=include_archive,
                )
                out = {
                    "view": "by_adapter",
                    "window_hours": window_hours,
                    "store_id": store_id or "(all stores)",
                    "adapters": list(raw.values()),
                }
            elif view == "recent_events":
                limit = max(
                    1, int(data.get("limit") or 100),
                )
                events = get_recent_events(
                    store_id=store_id,
                    limit=limit,
                    include_archive=include_archive,
                )
                out = {
                    "view": "recent_events",
                    "store_id": store_id or "(all stores)",
                    "limit": limit,
                    "events": events,
                }
            else:
                # "summary" / default
                out = {
                    "view": "summary",
                    "window_hours": window_hours,
                    "store_id": store_id or "(all stores)",
                    "summary": costs_total(
                        store_id=store_id,
                        window_hours=window_hours,
                        include_archive=include_archive,
                    ),
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "per_store_costs: query raised: %s", exc,
            )
            return self._fail(
                f"query raised: {exc}", 0.0,
            )

        return self._success(out, start)

    @staticmethod
    def _serialise_store_summary(s: Any) -> dict[str, Any]:
        return {
            "store_id": s.store_id,
            "total_cost_usd": round(s.total_cost_usd, 4),
            "total_calls": s.total_calls,
            "failed_calls": s.failed_calls,
            "failure_rate": round(s.failure_rate, 3),
            "avg_latency_ms": round(s.avg_latency_ms, 1),
            "by_adapter": s.by_adapter,
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
