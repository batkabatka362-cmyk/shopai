"""Store Strategist Engine — Pattern Q envelope."""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .reasoner import (
    collect_context,
    derive_recommendations,
    overall_verdict,
)

logger = logging.getLogger(__name__)


class StoreStrategistEngine:
    ENGINE_NAME = "store_strategist"

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

        store_id = str(data.get("store_id") or "")
        try:
            top = int(data.get("top", 0))
        except (TypeError, ValueError):
            top = 0

        ctx = collect_context(store_id)
        recs = derive_recommendations(ctx)
        if top > 0:
            recs = recs[:top]

        verdict = overall_verdict(ctx, recs)

        # W963-43: auto-record top recommendation into
        # persistent memory. Best-effort -- failure does NOT
        # break the strategist.
        if store_id and recs:
            try:
                from engines.strategist_memory import store as _mem
                top_rec = recs[0]
                _mem.record(
                    store_id=store_id,
                    signal=str(top_rec.source_signal or ""),
                    action=str(top_rec.action or ""),
                    drill_command=str(top_rec.drill_command or ""),
                    confidence=float(top_rec.confidence or 0.0),
                    impact=str(top_rec.impact or "medium"),
                    priority_score=float(
                        top_rec.priority_score or 0.0,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "store_strategist: memory record raised: %s",
                    exc,
                )

        return self._success(
            {
                "store_id": ctx.store_id,
                "niche": ctx.niche,
                "verdict": verdict,
                "context": {
                    "funnel_verdict": ctx.funnel_verdict,
                    "funnel_weakest": ctx.funnel_weakest,
                    "funnel_drop": ctx.funnel_drop,
                    "trajectory_verdict": ctx.trajectory_verdict,
                    "trajectory_slope_pct": ctx.trajectory_slope_pct,
                    "earning_count": ctx.earning_count,
                    "total_revenue_7d": ctx.total_revenue_7d,
                    "earning_engines": ctx.earning_engines,
                    "checkup_verdict": ctx.checkup_verdict,
                    "autonomy_overall": ctx.autonomy_overall,
                    "autonomy_paused": ctx.autonomy_paused,
                    "has_products": ctx.has_products,
                    "has_ads_wired": ctx.has_ads_wired,
                    "has_esp_wired": ctx.has_esp_wired,
                },
                "recommendations": [asdict(r) for r in recs],
                "recommendation_count": len(recs),
                "next_action": _next_action(verdict, recs),
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


def _next_action(verdict: str, recs: list) -> str:
    if not recs:
        return "No recommendations. Run shopai cycle run --yes."
    top = recs[0]
    if verdict == "intervene":
        return (
            f"Top priority: {top.action}. "
            f"Drill: {top.drill_command}"
        )
    if verdict == "active":
        return (
            f"Store earning. Top suggestion: {top.action}. "
            f"Drill: {top.drill_command}"
        )
    return (
        f"Waiting on signal. Suggested: {top.action}."
    )
