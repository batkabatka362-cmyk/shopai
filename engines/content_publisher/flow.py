"""Content Publisher Engine — flow orchestrator (W963-6).

Pattern Q canonical envelope. Read-only by default; --apply
opt-in routes to ApprovalQueue. Mirrors product_sourcer (W963-3).
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import asdict
from typing import Any

from .catalogs import (
    BlogCandidate,
    SUPPORTED_NICHES,
    catalog_summary,
    get_catalog,
)
from .draft_creator import (
    enqueue_articles_for_approval,
)

logger = logging.getLogger(__name__)


_DEFAULT_COUNT = 10
_MAX_COUNT = 50  # 50 candidates max per niche.


def _serialize(c: BlogCandidate) -> dict[str, Any]:
    return asdict(c)


class ContentPublisherEngine:
    """Read-only blog post candidate generator + optional
    approval-queue submission for DRAFT article creation."""

    ENGINE_NAME = "content_publisher"

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

        # Niche resolution.
        niche_raw = data.get("niche")
        if niche_raw is None or niche_raw == "":
            return self._empty(start)
        if not isinstance(niche_raw, str):
            return self._fail(
                "niche must be a string",
                time.monotonic() - start,
            )
        niche = niche_raw.strip().lower()
        if niche not in SUPPORTED_NICHES:
            return self._fail(
                f"unsupported niche '{niche}'. Choose from: "
                f"{', '.join(SUPPORTED_NICHES)}",
                time.monotonic() - start,
            )

        # Count resolution.
        try:
            count = int(data.get("count", _DEFAULT_COUNT))
        except (TypeError, ValueError):
            return self._fail(
                "count must be int",
                time.monotonic() - start,
            )
        if count < 1:
            return self._fail(
                "count must be >= 1",
                time.monotonic() - start,
            )
        count = min(count, _MAX_COUNT)

        catalog = get_catalog(niche)
        if not catalog:
            return self._fail(
                f"catalog empty for niche '{niche}'",
                time.monotonic() - start,
            )

        slice_size = min(count, len(catalog))
        candidates = catalog[:slice_size]
        serialized = [_serialize(c) for c in candidates]

        # Optional apply path.
        pending: list[dict[str, Any]] = []
        if data.get("apply_candidates") is True:
            # Bootstrap mandate: always require_approval=True.
            # Direct mint of articles would publish marketing
            # content without operator review — a "wait, I
            # didn't approve THAT" risk we explicitly avoid.
            blog_id = data.get("blog_id")
            pending = enqueue_articles_for_approval(
                serialized, niche=niche, blog_id=blog_id,
            )

        if pending:
            next_action = (
                f"{len(pending)} article(s) enqueued. Review: "
                "`shopai approvals pending` + approve via "
                "`shopai approvals approve-all "
                "--engine content_publisher --execute`."
            )
        elif data.get("apply_candidates") is True:
            next_action = (
                "Candidates generated but none enqueued "
                "(missing blog_id, approval queue rejected, "
                "or queue I/O error). Re-run with "
                "--blog-id <gid> to target a specific Shopify "
                "blog."
            )
        else:
            next_action = (
                "Review the candidates. To enqueue as DRAFT "
                "articles for approval, re-run with --apply "
                "(writes to approval queue, not Shopify "
                "directly)."
            )

        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "niche": niche,
                "count_requested": count,
                "count_returned": slice_size,
                "candidates": serialized,
                "pending_actions": pending,
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
        elapsed = time.monotonic() - start
        return {
            "status": "success",
            "data": {
                "niche": "",
                "count_requested": 0,
                "count_returned": 0,
                "candidates": [],
                "pending_actions": [],
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
