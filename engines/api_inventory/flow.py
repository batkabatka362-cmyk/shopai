"""API Inventory engine -- Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .inventory import build_inventory

logger = logging.getLogger(__name__)


class ApiInventoryEngine:
    ENGINE_NAME = "api_inventory"

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

        try:
            report = build_inventory()
        except Exception as exc:  # noqa: BLE001
            logger.debug("api_inventory: build raised: %s", exc)
            return self._fail(f"build raised: {exc}", 0.0)

        out = {
            "total_aliases": report.total_aliases,
            "configured_count": report.configured_count,
            "ready_for_launch": report.ready_for_launch,
            "headline": report.headline,
            "next_action": report.next_action,
            "categories": [
                {
                    "key": c.key,
                    "title": c.title,
                    "priority": c.priority,
                    "minimum": c.minimum,
                    "blocks_msg": c.blocks_msg,
                    "configured_count": c.configured_count,
                    "total_count": c.total_count,
                    "status": c.status,
                    "aliases": [asdict(a) for a in c.aliases],
                }
                for c in report.categories
            ],
        }
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
