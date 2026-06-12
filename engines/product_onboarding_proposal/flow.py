"""ProductOnboardingProposalEngine -- Pattern Q envelope.

Submits the proposal to the approval queue when
data.submit_to_queue=True, returns the markdown report
either way.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from .proposal import build_proposal, report_to_markdown

logger = logging.getLogger(__name__)


class ProductOnboardingProposalEngine:
    ENGINE_NAME = "product_onboarding_proposal"

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
                payload.get(
                    "error", "Upstream failure",
                ), 0.0,
            )

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        store_id = str(data.get("store_id") or "")
        if not store_id:
            return self._fail(
                "store_id required (per-store proposal)",
                0.0,
            )
        niche = str(data.get("niche") or "")
        count = int(data.get("count") or 10)
        window = float(
            data.get("window_hours") or 168.0,
        )
        submit = bool(data.get("submit_to_queue", False))

        try:
            report = build_proposal(
                store_id,
                niche=niche,
                count=count,
                window_hours=window,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "build_proposal raised: %s", exc,
            )
            return self._fail(
                f"build_proposal raised: {exc}", 0.0,
            )

        report_md = report_to_markdown(report)

        action_id = ""
        if submit and report.candidates:
            try:
                action_id = self._submit_to_queue(
                    store_id=store_id,
                    niche=niche,
                    report_md=report_md,
                    candidates=[
                        {
                            "title": c.title,
                            "supplier": c.supplier,
                            "supplier_id": c.supplier_id,
                            "cost_usd": c.cost_usd,
                            "suggested_retail_usd": (
                                c.suggested_retail_usd
                            ),
                            "risk_flags": c.risk_flags,
                        }
                        for c in report.candidates
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "approval queue submit raised: %s",
                    exc,
                )

        out = {
            "store_id": store_id,
            "niche": niche,
            "discovered_count": report.discovered_count,
            "proposed_count": len(report.candidates),
            "total_inventory_cost_usd": (
                report.total_inventory_cost_usd
            ),
            "avg_projected_margin_pct": (
                report.average_margin_pct
            ),
            "notes": report.notes,
            "candidates": [
                {
                    "title": c.title,
                    "supplier": c.supplier,
                    "cost_usd": c.cost_usd,
                    "suggested_retail_usd": (
                        c.suggested_retail_usd
                    ),
                    "projected_margin_pct": (
                        c.projected_margin_pct
                    ),
                    "niche_match_score": (
                        c.niche_match_score
                    ),
                    "risk_flags": c.risk_flags,
                    "reason": c.reason,
                }
                for c in report.candidates
            ],
            "report_markdown": report_md,
            "approval_action_id": action_id,
        }
        return self._success(out, start)

    @staticmethod
    def _submit_to_queue(
        *,
        store_id: str,
        niche: str,
        report_md: str,
        candidates: list[dict[str, Any]],
    ) -> str:
        """Enqueue a single batch-approval action.
        Approval == 'import all listed candidates'.
        Rejection == 'discard the batch'."""
        from core.approval import get_approval_queue
        queue = get_approval_queue()
        action = queue.enqueue(
            engine="product_onboarding_proposal",
            action_type="propose_product_batch",
            capability="SHOPIFY_CREATE_PRODUCT",
            params={
                "niche": niche,
                "candidates": candidates,
            },
            narrative=report_md,
            confidence=0.85,
            store_id=store_id,
        )
        return getattr(action, "id", "") or ""

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
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
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
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
                ),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
