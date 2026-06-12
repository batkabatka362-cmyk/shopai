"""PerStoreCredsEngine -- Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from .coverage import discover_coverage

logger = logging.getLogger(__name__)


class PerStoreCredsEngine:
    ENGINE_NAME = "per_store_creds"

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
                payload.get("error", "Upstream failure"),
                0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        only_store = str(data.get("store_id") or "")

        try:
            coverage = discover_coverage(
                only_store=only_store,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "per_store_creds query raised: %s", exc,
            )
            return self._fail(
                f"query raised: {exc}", 0.0,
            )

        out = {
            "store_id": only_store or "(all stores)",
            "store_count": len(coverage),
            "stores_with_overrides": sum(
                1 for c in coverage
                if c.override_count > 0
            ),
            "stores_using_fleet": sum(
                1 for c in coverage
                if c.override_count == 0
            ),
            "stores": [
                {
                    "store_id": c.store_id,
                    "override_count": c.override_count,
                    "overrides": c.overrides,
                }
                for c in coverage
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
