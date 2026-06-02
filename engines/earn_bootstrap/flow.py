"""Earn-Bootstrap orchestrator. Chains the W963 family.

Pattern Q canonical envelope. Read-only by default. With
``apply=True`` it forwards into product_sourcer's queue path.

Input ``data``:
    niche      — required (beauty / fashion / home / tech / food)
    count      — int, default 20
    apply      — bool, default False (preview only)
    store_id   — optional, threaded into the diagnostic

Output ``data``:
    diagnostic       — full revenue_readiness output
    candidates       — short summary of product candidates
                       (count, top 5 names, price range)
    pending_actions  — list of {pending_action_id, name} when
                       apply=True succeeded
    chain_verdict    — overall verdict: ready / cold_seeded /
                       cold_pending / cold_skipped / partial /
                       unknown
    next_steps       — operator-facing checklist of what to
                       do next
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

from engines.product_sourcer import ProductSourcerEngine
from engines.product_sourcer.catalogs import SUPPORTED_NICHES
from engines.revenue_readiness import RevenueReadinessEngine

logger = logging.getLogger(__name__)


_DEFAULT_COUNT = 20


class EarnBootstrapEngine:
    """One-command cold-start orchestrator."""

    ENGINE_NAME = "earn_bootstrap"

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

        # ── Stage 1: Diagnostic ───────────────────────────
        diagnostic_input: dict[str, Any] = {"data": {}}
        if data.get("store_id"):
            diagnostic_input["data"]["store_id"] = data["store_id"]
        diagnostic = RevenueReadinessEngine().run(diagnostic_input)
        diag_data = (
            diagnostic.get("data")
            if isinstance(diagnostic, dict) else None
        ) or {}
        verdict = diag_data.get("verdict") or "unknown"

        # Already earning — no chain to run.
        if verdict == "earning_active":
            return self._return(
                start=start,
                diagnostic=diag_data,
                candidates_summary={},
                pending_actions=[],
                chain_verdict="ready",
                next_steps=[
                    "All 6 readiness gates pass. Monitor via "
                    "`shopai earnings` + `shopai daily-brief`.",
                ],
            )

        # ── Stage 2: pick the gap to fill ─────────────────
        # For W963-5 we only auto-act on the has_products gate
        # since that's the cold-start unblocker we've already
        # built the substrate for. Other gaps (ad-spend, etc)
        # require credentials and remain manual.
        gates = diag_data.get("gates") or []
        product_gate_status = "unknown"
        for g in gates:
            if g.get("name") == "has_products":
                product_gate_status = g.get("status", "unknown")
                break

        if product_gate_status == "ready":
            # Products exist — bootstrap can't add value on the
            # product side. Punt with diagnostic-driven next-
            # action.
            return self._return(
                start=start,
                diagnostic=diag_data,
                candidates_summary={},
                pending_actions=[],
                chain_verdict="partial",
                next_steps=[
                    "Products exist; other gates need action. "
                    "See `shopai revenue-readiness` next_action.",
                    f"Top recommendation: {diag_data.get('next_action', '')}",
                ],
            )

        # ── Stage 3: niche resolution ─────────────────────
        niche_raw = data.get("niche")
        if not niche_raw:
            return self._return(
                start=start,
                diagnostic=diag_data,
                candidates_summary={},
                pending_actions=[],
                chain_verdict="cold_skipped",
                next_steps=[
                    "Bootstrap requires --niche to seed "
                    "products. Choose one: "
                    + ", ".join(SUPPORTED_NICHES),
                ],
            )

        # Count + apply resolution.
        try:
            count = int(data.get("count", _DEFAULT_COUNT))
        except (TypeError, ValueError):
            count = _DEFAULT_COUNT
        if count < 1:
            count = _DEFAULT_COUNT

        apply_flag = bool(data.get("apply", False))

        # ── Stage 4: product candidates ───────────────────
        ps_input: dict[str, Any] = {
            "data": {
                "niche": niche_raw, "count": count,
            },
        }
        if apply_flag:
            ps_input["data"]["apply_candidates"] = True
            # Always queue — never direct-mint from bootstrap.
            # A direct mint is reserved for dev / seed scripts;
            # the operator's day-1 chain MUST go through the
            # approval queue for visibility.
            ps_input["data"]["require_approval"] = True

        ps_result = ProductSourcerEngine().run(ps_input)
        ps_data = (
            ps_result.get("data")
            if isinstance(ps_result, dict) else None
        ) or {}

        if ps_result.get("status") != "success":
            return self._return(
                start=start,
                diagnostic=diag_data,
                candidates_summary={},
                pending_actions=[],
                chain_verdict="cold_skipped",
                next_steps=[
                    "Product candidate generation failed: "
                    + str(ps_result.get("error", "unknown")),
                ],
            )

        candidates = ps_data.get("candidates") or []
        pending = ps_data.get("pending_actions") or []

        candidates_summary = {
            "count": len(candidates),
            "top_names": [
                c.get("name", "") for c in candidates[:5]
            ],
            "price_range": {
                "min": min(
                    (c.get("price_min", 0) for c in candidates),
                    default=0,
                ),
                "max": max(
                    (c.get("price_max", 0) for c in candidates),
                    default=0,
                ),
            },
        }

        if apply_flag and pending:
            return self._return(
                start=start,
                diagnostic=diag_data,
                candidates_summary=candidates_summary,
                pending_actions=pending,
                chain_verdict="cold_seeded",
                next_steps=[
                    f"Enqueued {len(pending)} DRAFT-product "
                    "creates. Review them: "
                    "`shopai approvals pending`",
                    "Bulk-approve when satisfied: "
                    "`shopai approvals approve-all`",
                    "Activate DRAFT -> ACTIVE in Shopify Admin "
                    "to make them shoppable.",
                    "Then measure: `shopai earnings`",
                ],
            )

        if apply_flag and not pending:
            return self._return(
                start=start,
                diagnostic=diag_data,
                candidates_summary=candidates_summary,
                pending_actions=[],
                chain_verdict="cold_skipped",
                next_steps=[
                    "Candidates generated but none enqueued "
                    "(approval queue rejected the batch).",
                    "Manually inspect: `shopai product-candidates "
                    f"--niche {niche_raw} --json`",
                ],
            )

        # Default: preview-only mode.
        return self._return(
            start=start,
            diagnostic=diag_data,
            candidates_summary=candidates_summary,
            pending_actions=[],
            chain_verdict="cold_pending",
            next_steps=[
                f"{len(candidates)} candidate(s) generated for "
                f"niche={niche_raw}. Preview only.",
                f"Re-run with --yes to enqueue: "
                f"`shopai earn-bootstrap --niche {niche_raw} "
                f"--count {count} --yes`",
            ],
        )

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

    def _return(
        self, *, start: float, diagnostic: dict[str, Any],
        candidates_summary: dict[str, Any],
        pending_actions: list[dict[str, Any]],
        chain_verdict: str, next_steps: list[str],
    ) -> dict[str, Any]:
        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "diagnostic": diagnostic,
                "candidates_summary": candidates_summary,
                "pending_actions": pending_actions,
                "chain_verdict": chain_verdict,
                "next_steps": next_steps,
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
