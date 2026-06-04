"""W963-3: product_sourcer draft creator.

Phase 2 of the cold-start product pipeline. W963-2 generated
candidates as a recommendation; this module turns the list into
actual Shopify DRAFT products via either:

  1. Direct mint (legacy, unsafe for empire-scale):
     ``data.apply_candidates=True + data.require_approval=False``
     Calls SHOPIFY_CREATE_PRODUCT immediately for each candidate.

  2. Approval-queue mint (default safe):
     ``data.apply_candidates=True + data.require_approval=True``
     Enqueues each candidate as a pending_action; an operator
     reviews + approves via ``shopai approvals approve <id>`` and
     the executor (existing approval flow) replays the create.

Mirrors the pattern in engines/loyalty/discount_minter.py — Pattern
Z (record_writeback) compliant, Pattern J guards inherited from the
recorder.

The created products are always DRAFT — never ACTIVE. The operator
must explicitly transition draft -> active in Shopify Admin (or via
a future ``--publish`` flag). This keeps a human in the loop for
the FIRST product publish even when the rest of the cycle is
autonomous; an early mis-launched product is hard to undo.
"""
from __future__ import annotations

import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


_ENGINE = "product_sourcer"
_ACTION_TYPE = "create_draft_product"
_CAPABILITY = "SHOPIFY_CREATE_PRODUCT"


def _candidate_to_params(
    candidate: dict[str, Any], *, niche: str,
) -> dict[str, Any]:
    """Translate a serialized ProductCandidate into the friendly
    call shape that ShopifyProductsAdapter._create expects."""
    name = str(candidate.get("name") or "").strip()
    description = str(candidate.get("description") or "").strip()
    category = str(candidate.get("category") or "").strip()
    tags = candidate.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    # Always wrap description in <p>...</p> so the body_html
    # Shopify expects renders correctly even when descriptions
    # are bare text.
    body_html = (
        f"<p>{description}</p>" if description else ""
    )
    return {
        "title": name,
        "description": body_html,
        "status": "DRAFT",
        "vendor": "ShopAI",
        "product_type": category,
        "tags": [
            t for t in tags
            if isinstance(t, str) and t
        ],
        # W963-3: structured metadata so the future executor can
        # join back to the source catalog (niche + suggested
        # price band) without re-deriving.
        "_metadata": {
            "source": "product_sourcer",
            "niche": niche,
            "suggested_price": candidate.get("suggested_price"),
            "price_min": candidate.get("price_min"),
            "price_max": candidate.get("price_max"),
        },
    }


def _build_narrative(
    candidate: dict[str, Any], niche: str,
) -> str:
    name = candidate.get("name") or "(unnamed)"
    price = candidate.get("suggested_price") or 0
    return (
        f"Create DRAFT product '{name}' "
        f"(niche={niche}, suggested ${price:.2f})"
    )


def enqueue_drafts_for_approval(
    candidates: list[dict[str, Any]], *, niche: str,
) -> list[dict[str, Any]]:
    """Enqueue every candidate as a pending_action. Safe-by-
    default path for empire-scale runs.

    Returns one entry per successfully-enqueued candidate:
        {"pending_action_id", "narrative", "params"}

    Candidates that fail enqueue (queue I/O error, missing
    required field) are silently skipped — they appear in the
    `skipped` list of the caller's aggregate via the reason
    `enqueue_failed`.
    """
    if not isinstance(candidates, list):
        return []

    out: list[dict[str, Any]] = []
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_sourcer: approval queue import failed: %s",
            exc,
        )
        return []

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        if not cand.get("name"):
            continue
        params = _candidate_to_params(cand, niche=niche)
        narrative = _build_narrative(cand, niche)
        try:
            action = queue.enqueue(
                engine=_ENGINE,
                action_type=_ACTION_TYPE,
                capability=_CAPABILITY,
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_sourcer: enqueue raised for '%s': %s",
                cand.get("name"), exc,
            )
            continue
        out.append({
            "pending_action_id": action.id,
            "narrative": narrative,
            "params": params,
        })
    return out


def mint_drafts_immediately(
    candidates: list[dict[str, Any]], *, niche: str,
) -> list[dict[str, Any]]:
    """Direct-mint variant. Calls SHOPIFY_CREATE_PRODUCT for
    every candidate WITHOUT approval-queue gating.

    Use only when the operator has explicitly opted out of the
    queue (e.g. dev seed scripts). Each mint goes through
    record_writeback per Pattern Z so the autonomous loop sees
    the outcome.

    Returns one entry per attempted mint:
        {"product_id" | None, "status", "narrative",
         "params", "error"}

    Skip semantics:
      - empty candidate / no name -> ``status="skipped"``
      - router unavailable        -> ``status="router_missing"``
      - adapter failure           -> ``status="error"`` + error text
    """
    if not isinstance(candidates, list):
        return []

    out: list[dict[str, Any]] = []
    try:
        from core.adapters.router import get_router
        from core.adapters.base import Capability
        router = get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_sourcer: router import failed: %s", exc,
        )
        # All mints fail the same way. Pattern Z: record each
        # attempt so the autonomous loop sees the substrate
        # failure -- previously this branch silently skipped
        # the recorder.
        for cand in candidates:
            if not isinstance(cand, dict) or not cand.get("name"):
                continue
            params = _candidate_to_params(cand, niche=niche)
            adapter_params = {
                k: v for k, v in params.items()
                if not k.startswith("_")
            }
            try:
                record_writeback(
                    engine=_ENGINE,
                    action_type=_ACTION_TYPE,
                    capability=_CAPABILITY,
                    params=adapter_params,
                    success=False,
                    error="smart router unavailable",
                )
            except Exception as rwe:  # noqa: BLE001
                logger.debug(
                    "product_sourcer: writeback raised: %s",
                    rwe,
                )
            out.append({
                "product_id": None,
                "status": "router_missing",
                "narrative": _build_narrative(cand, niche),
                "params": params,
                "error": "smart router unavailable",
            })
        return out

    capability = Capability.SHOPIFY_CREATE_PRODUCT
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        if not cand.get("name"):
            out.append({
                "product_id": None,
                "status": "skipped",
                "narrative": "(missing name)",
                "params": {},
                "error": "candidate has no name",
            })
            continue
        params = _candidate_to_params(cand, niche=niche)
        narrative = _build_narrative(cand, niche)

        # The adapter doesn't accept _metadata; strip before
        # the GraphQL call but keep on the entry returned to
        # the caller.
        adapter_params = {
            k: v for k, v in params.items()
            if not k.startswith("_")
        }

        result = None
        adapter_error: str | None = None
        try:
            result = router.execute(capability, adapter_params)
        except Exception as exc:  # noqa: BLE001
            adapter_error = (
                f"{type(exc).__name__}: {str(exc)[:120]}"
            )

        success = (
            result is not None
            and getattr(result, "ok", False)
        )
        product_id = None
        if success:
            payload = (
                getattr(result, "data", None) or {}
            )
            if isinstance(payload, dict):
                product_id = (
                    payload.get("product_id")
                    or payload.get("id")
                )

        # Pattern Z: record every attempt (success + failure).
        try:
            record_writeback(
                engine=_ENGINE,
                action_type=_ACTION_TYPE,
                capability=_CAPABILITY,
                params=adapter_params,
                success=bool(success),
                error=(
                    adapter_error
                    if adapter_error
                    else (
                        None if success
                        else getattr(result, "error", None)
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_sourcer: record_writeback raised: %s",
                exc,
            )

        out.append({
            "product_id": product_id,
            "status": "minted" if success else "error",
            "narrative": narrative,
            "params": params,
            "error": (
                adapter_error
                if adapter_error
                else (
                    None if success
                    else getattr(result, "error", "adapter failed")
                )
            ),
        })
    return out
