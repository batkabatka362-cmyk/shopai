"""Revenue Readiness Engine — flow orchestrator.

Diagnostic only. Returns the Pattern Q canonical envelope:

    {
      status: "success" | "error",
      data: {
        store_id, verdict, passed, total, gates: [...], next_action
      },
      meta: {engine, timestamp, elapsed_seconds},
      error: str | None,
    }

``store_id`` is optional. When supplied, the engine pulls per-
store stats via StoreManager.get_stats; when omitted (or the
store can't be looked up) the engine falls back to whatever the
caller passes in ``input_payload.data.stats`` so it's still
testable without a live Shopify connection.
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .analyzer import ReadinessReport, analyze

logger = logging.getLogger(__name__)


class RevenueReadinessEngine:
    """Read-only revenue-readiness diagnostic."""

    ENGINE_NAME = "revenue_readiness"

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

        store_id = data.get("store_id")
        store_id = str(store_id) if store_id else None

        stats = data.get("stats")
        if not isinstance(stats, dict):
            stats = self._resolve_stats(store_id)

        report = analyze(stats=stats, store_id=store_id)
        elapsed = time.monotonic() - start
        return self._success(report, elapsed)

    # ── Internal ──────────────────────────────────────────────

    @staticmethod
    def _safe_copy(payload: Any) -> Any:
        if payload is None:
            return {}
        try:
            return copy.deepcopy(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("input copy raised: %s", exc)
            return None

    @staticmethod
    def _resolve_stats(store_id: str | None) -> dict[str, Any]:
        """Pull per-store stats from StoreManager when possible.
        Returns zeros when the store can't be looked up so the
        analyzer still produces a valid report."""
        if not store_id:
            return {
                "products": 0,
                "orders": 0,
                "customers": 0,
                "total_revenue": 0.0,
            }
        # W963-1.1: correct import path. Pre-fix used
        # ``core.stores.manager`` which doesn't exist; the bare
        # except below swallowed the ImportError so every per-
        # store probe returned zero stats regardless of reality.
        stats = {}
        for module_path in (
            "data_pipeline.store.store_manager",
            "execution.shopify.store_manager",
        ):
            try:
                mod = __import__(
                    module_path, fromlist=["StoreManager"],
                )
                sm = mod.StoreManager()
                stats = sm.get_stats(store_id) or {}
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "revenue_readiness stats lookup raised "
                    "for %s: %s", module_path, exc,
                )
        return {
            "products": int(stats.get("products", 0) or 0),
            "orders": int(stats.get("orders", 0) or 0),
            "customers": int(stats.get("customers", 0) or 0),
            "total_revenue": float(
                stats.get("total_revenue", 0.0) or 0.0,
            ),
        }

    def _success(
        self, report: ReadinessReport, elapsed: float,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "data": {
                "store_id": report.store_id,
                "verdict": report.verdict,
                "passed": report.passed_count(),
                "total": report.total_count(),
                "gates": [asdict(g) for g in report.gates],
                "next_action": report.next_action,
            },
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
