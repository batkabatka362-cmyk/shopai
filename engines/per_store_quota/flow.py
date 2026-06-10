"""PerStoreQuotaEngine -- Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .tracker import (
    compute_all_snapshots,
    compute_snapshot,
    critical_stores,
    warn_stores,
)

logger = logging.getLogger(__name__)


class PerStoreQuotaEngine:
    ENGINE_NAME = "per_store_quota"

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
                data.get("window_hours", 24.0),
            )
        except (TypeError, ValueError):
            window_hours = 24.0
        store_id = str(data.get("store_id") or "")
        adapter = str(data.get("adapter") or "")
        view = str(
            data.get("view") or "all",
        ).lower()

        try:
            if store_id and view == "single":
                snap = compute_snapshot(
                    store_id, adapter=adapter,
                    window_hours=window_hours,
                )
                out = {
                    "view": "single",
                    "store_id": store_id,
                    "adapter": adapter or "(all)",
                    "window_hours": window_hours,
                    "snapshot": self._serialise(snap),
                }
            elif view == "critical":
                snaps = critical_stores(
                    window_hours=window_hours,
                )
                out = {
                    "view": "critical",
                    "window_hours": window_hours,
                    "count": len(snaps),
                    "snapshots": [
                        self._serialise(s) for s in snaps
                    ],
                }
            elif view == "warn":
                snaps = warn_stores(
                    window_hours=window_hours,
                )
                out = {
                    "view": "warn",
                    "window_hours": window_hours,
                    "count": len(snaps),
                    "snapshots": [
                        self._serialise(s) for s in snaps
                    ],
                }
            else:
                # "all"
                snaps = compute_all_snapshots(
                    window_hours=window_hours,
                )
                out = {
                    "view": "all",
                    "window_hours": window_hours,
                    "total_snapshots": len(snaps),
                    "critical_count": sum(
                        1 for s in snaps
                        if s.state.value == "critical"
                    ),
                    "warn_count": sum(
                        1 for s in snaps
                        if s.state.value == "warn"
                    ),
                    "snapshots": [
                        self._serialise(s) for s in snaps
                    ],
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "per_store_quota query raised: %s", exc,
            )
            return self._fail(
                f"query raised: {exc}", 0.0,
            )

        return self._success(out, start)

    @staticmethod
    def _serialise(s: Any) -> dict[str, Any]:
        return {
            "store_id": s.store_id,
            "adapter": s.adapter or "(all adapters)",
            "spend_usd": s.spend_usd,
            "cap_usd": s.cap_usd,
            "headroom_usd": s.headroom_usd,
            "warn_ratio": s.warn_ratio,
            "state": s.state.value,
            "pct_used": round(s.pct_used, 1),
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
