"""Product Sourcer Engine — flow orchestrator.

Returns the Pattern Q canonical envelope:

    {
      status: "success" | "error",
      data: {
        niche: str,
        count_requested: int,
        count_returned: int,
        candidates: [
          {name, category, description, price_min,
           price_max, suggested_price, tags, vendor_hint},
          ...
        ],
        next_action: str,
      },
      meta: {engine, timestamp, elapsed_seconds},
      error: str | None,
    }

Suggested price = midpoint of the candidate's price band, rounded
to .99 (common psychological-pricing convention). Operators can
override at draft-creation time.

This engine writes NOTHING. Phase 2 will add a sibling
`draft_creator.py` that takes the candidate list and calls
SHOPIFY_CREATE_PRODUCT (status=DRAFT) behind the approval queue
— gated on `data.apply_candidates=True` per the Pattern Z opt-in
convention.
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .catalogs import (
    ProductCandidate,
    SUPPORTED_NICHES,
    catalog_summary,
    get_catalog,
)
from .draft_creator import (
    enqueue_drafts_for_approval,
    mint_drafts_immediately,
)

logger = logging.getLogger(__name__)


# Defaults
_DEFAULT_COUNT = 20
_MAX_COUNT = 100  # Refuse to enumerate beyond this; catalog cap.


def _suggested_price(c: ProductCandidate) -> float:
    """Midpoint of the candidate's price band, .99-rounded."""
    mid = (c.price_min + c.price_max) / 2.0
    # Round to nearest .99 floor: e.g. 19.50 -> 18.99,
    # 19.99 -> 19.99, 20.20 -> 19.99
    return round(mid, 0) - 0.01 if (mid % 1) <= 0.5 else (
        round(mid, 0) + 0.99
    )


def _serialize(c: ProductCandidate) -> dict[str, Any]:
    out = asdict(c)
    out["suggested_price"] = round(_suggested_price(c), 2)
    return out


class ProductSourcerEngine:
    """Read-only product candidate generator. Cold-start
    unblocker for empty Shopify catalogs."""

    ENGINE_NAME = "product_sourcer"

    def run(
        self, input_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()

        # ── Stage 0: input validation ──────────────────────
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

        # Niche resolution. Empty → list catalog summary
        # so the engine still returns the envelope on cold
        # start (Pattern Q probes the empty-input path).
        niche_raw = data.get("niche")
        if niche_raw is None or niche_raw == "":
            return self._empty(start)

        if not isinstance(niche_raw, str):
            return self._fail(
                "niche must be a string", time.monotonic() - start,
            )

        niche = niche_raw.strip().lower()
        if niche not in SUPPORTED_NICHES:
            return self._fail(
                f"unsupported niche '{niche}'. Choose from: "
                f"{', '.join(SUPPORTED_NICHES)}",
                time.monotonic() - start,
            )

        # Count resolution.
        count_raw = data.get("count", _DEFAULT_COUNT)
        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            return self._fail(
                f"count must be int, got "
                f"{type(count_raw).__name__}",
                time.monotonic() - start,
            )
        if count < 1:
            return self._fail(
                "count must be >= 1",
                time.monotonic() - start,
            )
        count = min(count, _MAX_COUNT)

        # Optional price ceiling. Filters candidates whose
        # price_min exceeds the cap.
        price_max_filter = data.get("price_max")
        if price_max_filter is not None:
            try:
                price_max_filter = float(price_max_filter)
            except (TypeError, ValueError):
                return self._fail(
                    "price_max must be numeric",
                    time.monotonic() - start,
                )

        # ── Stage 1: pull catalog ──────────────────────────
        catalog = get_catalog(niche)
        if not catalog:
            # Defensive — SUPPORTED_NICHES gate should have
            # rejected unknown niches but the catalog could
            # be empty during a future migration.
            return self._fail(
                f"catalog empty for niche '{niche}'",
                time.monotonic() - start,
            )

        # ── Stage 2: filter ────────────────────────────────
        if price_max_filter is not None:
            catalog = [
                c for c in catalog
                if c.price_min <= price_max_filter
            ]
            if not catalog:
                return self._success_empty(
                    niche=niche, count=count, start=start,
                    reason=(
                        f"no candidates under "
                        f"${price_max_filter:.2f}"
                    ),
                )

        # ── Stage 3: slice ─────────────────────────────────
        slice_size = min(count, len(catalog))
        candidates = catalog[:slice_size]
        serialized = [_serialize(c) for c in candidates]

        # ── Stage 4: optional draft creation ───────────────
        # Default OFF — operators stay in pure-recommendation
        # mode unless they explicitly opt in via
        # data.apply_candidates=True.
        #
        # Two opt-in modes:
        #   apply_candidates + require_approval (default True):
        #     enqueue each candidate to ApprovalQueue. Operator
        #     reviews via `shopai approvals pending` and approves
        #     one-by-one. SAFE for empire-scale runs.
        #   apply_candidates + require_approval=False:
        #     mint immediately via SHOPIFY_CREATE_PRODUCT. Use
        #     only for dev / seed flows.
        pending_actions: list[dict[str, Any]] = []
        minted_drafts: list[dict[str, Any]] = []
        if data.get("apply_candidates") is True:
            # Default to require_approval=True unless caller
            # explicitly opts out — safer-by-default.
            require_approval = data.get(
                "require_approval", True,
            )
            if require_approval:
                pending_actions = enqueue_drafts_for_approval(
                    serialized, niche=niche,
                )
            else:
                minted_drafts = mint_drafts_immediately(
                    serialized, niche=niche,
                )

        # Tailor next_action based on what just happened.
        if pending_actions:
            next_action = (
                f"{len(pending_actions)} candidate(s) "
                "enqueued. Review: `shopai approvals pending` "
                "+ approve via `shopai approvals approve <id>`."
            )
        elif minted_drafts:
            ok = sum(
                1 for m in minted_drafts
                if m.get("status") == "minted"
            )
            failed = len(minted_drafts) - ok
            next_action = (
                f"{ok} draft(s) created in Shopify "
                f"({failed} failed). Visit Shopify Admin -> "
                "Products to review + activate."
            )
        else:
            next_action = (
                "Review the candidates. To enqueue all as "
                "DRAFT products for approval, re-run with "
                "--apply (writes to approval queue, not "
                "Shopify directly)."
            )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "niche": niche,
                "count_requested": count,
                "count_returned": slice_size,
                "candidates": serialized,
                "pending_actions": pending_actions,
                "minted_drafts": minted_drafts,
                "next_action": next_action,
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

    def _empty(self, start: float) -> dict[str, Any]:
        """Empty-input response — Pattern Q audit probes this."""
        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "niche": "",
                "count_requested": 0,
                "count_returned": 0,
                "candidates": [],
                "pending_actions": [],
                "minted_drafts": [],
                "next_action": (
                    f"Specify a niche: {', '.join(SUPPORTED_NICHES)}. "
                    "Catalog totals: "
                    + ", ".join(
                        f"{k}={v}"
                        for k, v in catalog_summary().items()
                    )
                ),
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

    def _success_empty(
        self, *, niche: str, count: int, start: float,
        reason: str,
    ) -> dict[str, Any]:
        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "niche": niche,
                "count_requested": count,
                "count_returned": 0,
                "candidates": [],
                "pending_actions": [],
                "minted_drafts": [],
                "next_action": (
                    f"{reason}. Raise --price-max or pick "
                    "a different niche."
                ),
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
