"""Legal Document Engine — Shopify page applier (multi-doc).

The legal_document engine emits a list of compliance-ready
documents (privacy policy, terms of service, refund policy,
shipping policy, etc.). Each carries ``{type, title, content,
sections, last_updated, html_content}`` — fully-rendered HTML
ready to publish. Pre-fix the merchant had to copy each
document into a Shopify page by hand, set up the handle
(``privacy-policy``, ``terms-of-service``, etc.), and
republish whenever ShopAI regenerated.

This applier closes the loop. Per document, create an
UNPUBLISHED Shopify page via SHOPIFY_CREATE_PAGE; the
merchant reviews each in admin before publishing.
Unlike landing_page's single-best-variant pick, legal_document
mints ONE page per document type — privacy + terms + refund +
shipping are all distinct pages, all needed for compliance.

UNPUBLISHED-by-default (``is_published=False``) because:
  * Legal copy lands LIVE the moment it's published — a typo
    in a privacy policy is a compliance risk. Staged gives
    the merchant a review pass.
  * Same risk gradient as landing_page (#85) and bundle (#84).

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_legal_docs=True + data.require_approval=False
    → SHOPIFY_CREATE_PAGE immediately per document
  data.apply_legal_docs=True + data.require_approval=True
    → enqueue each document to core.approval; merchant
      approves before each mutation lands

Skipped (no API call / no queue entry) when:
  * Documents list is empty.
  * Document missing title / html_content (can't render a
    blank page).
  * Compliance check is failing for the document
    (``compliance_check.{doc_type}.status == "fail"``) — block
    the writeback rather than publish a known-bad policy.
  * Router unavailable / adapter rejects (per-document, doesn't
    halt the batch).
  * Approval queue unavailable (approval path).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.legal_document.applier")


# Type → handle prefix mapping. Falls back to slugified type
# when the document type isn't in this table.
_HANDLE_DEFAULTS = {
    "privacy_policy": "privacy-policy",
    "terms_of_service": "terms-of-service",
    "terms_and_conditions": "terms-of-service",
    "refund_policy": "refund-policy",
    "return_policy": "refund-policy",
    "shipping_policy": "shipping-policy",
    "cookie_policy": "cookie-policy",
}


def apply_legal_documents(
    documents: list[dict[str, Any]],
    compliance_check: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Create an unpublished Shopify page per legal document.

    Returns per-document list with ``{type, title, applied,
    page_id, handle, is_published, error}``. ``applied=True``
    when the SHOPIFY_CREATE_PAGE mutation succeeded.
    """
    proposals = _build_proposals(documents, compliance_check)
    if not proposals:
        return []

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        return [
            {
                "type": p["type"],
                "title": p["title"],
                "applied": False,
                "page_id": "",
                "handle": p["handle"],
                "is_published": False,
                "error": "router_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        recorder_params = {
            "type": p["type"],
            "title": p["title"],
            "handle": p["handle"],
        }
        try:
            result = router.execute(capability, p["adapter_params"])
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_legal_documents raised for %s: %s",
                p["type"], exc,
            )
            record_writeback(
                engine="legal_document",
                action_type="apply_legal_document",
                capability="SHOPIFY_CREATE_PAGE",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "type": p["type"],
                "title": p["title"],
                "applied": False,
                "page_id": "",
                "handle": p["handle"],
                "is_published": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            record_writeback(
                engine="legal_document",
                action_type="apply_legal_document",
                capability="SHOPIFY_CREATE_PAGE",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "type": p["type"],
                "title": p["title"],
                "applied": False,
                "page_id": "",
                "handle": p["handle"],
                "is_published": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        data = getattr(result, "data", {}) or {}
        page = data.get("page") or {}
        record_writeback(
            engine="legal_document",
            action_type="apply_legal_document",
            capability="SHOPIFY_CREATE_PAGE",
            params=recorder_params,
            success=True,
        )
        results.append({
            "type": p["type"],
            "title": page.get("title", p["title"]),
            "applied": True,
            "page_id": page.get("id", "") or "",
            "handle": page.get("handle", p["handle"]),
            "is_published": bool(page.get("is_published", False)),
            "error": None,
        })

    return results


def enqueue_legal_documents_for_approval(
    documents: list[dict[str, Any]],
    compliance_check: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-engine alternative to :func:`apply_legal_documents`.

    Same upfront filters; each entry returned carries a
    ``pending_action_id`` in place of the eventual page_id.
    """
    proposals = _build_proposals(documents, compliance_check)
    if not proposals:
        return []

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "type": p["type"],
                "title": p["title"],
                "applied": False,
                "page_id": "",
                "handle": p["handle"],
                "is_published": False,
                "error": "approval_queue_unavailable",
                "pending_action_id": None,
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        narrative = (
            f"Create staged legal page '{p['title']}' "
            f"(type: {p['type']}, handle: {p['handle']})"
        )
        params = {
            "type": p["type"],
            "title": p["title"],
            "handle": p["handle"],
            "adapter_params": p["adapter_params"],
        }
        try:
            action = queue.enqueue(
                engine="legal_document",
                action_type="apply_legal_document",
                capability="SHOPIFY_CREATE_PAGE",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "enqueue raised for %s: %s", p["type"], exc,
            )
            results.append({
                "type": p["type"],
                "title": p["title"],
                "applied": False,
                "page_id": "",
                "handle": p["handle"],
                "is_published": False,
                "error": f"enqueue_raised: {exc}",
                "pending_action_id": None,
            })
            continue

        results.append({
            "type": p["type"],
            "title": p["title"],
            "applied": False,
            "page_id": "",
            "handle": p["handle"],
            "is_published": False,
            "error": "queued",
            "pending_action_id": action.id,
        })

    return results


# ── Proposal builder ──────────────────────────────────────────


def _build_proposals(
    documents: list[dict[str, Any]] | None,
    compliance_check: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Walk documents and produce one adapter-ready proposal
    per valid doc.

    Filters:
      * Missing title or html_content (blank page is useless).
      * Compliance fail (block publishing known-bad policies).
    """
    if not isinstance(documents, list):
        return []

    out: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_type = str(doc.get("type", "")).strip().lower()
        title = str(doc.get("title", "")).strip()
        html_content = str(doc.get("html_content", "")).strip()
        if not title or not html_content:
            continue
        if _is_compliance_failed(doc_type, compliance_check):
            continue

        handle = _resolve_handle(doc_type, title)
        adapter_params: dict[str, Any] = {
            "title": title[:200],
            "body_html": html_content,
            "is_published": False,
        }
        if handle:
            adapter_params["handle"] = handle

        out.append({
            "type": doc_type or "unknown",
            "title": title[:200],
            "handle": handle,
            "html_content": html_content,
            "adapter_params": adapter_params,
        })
    return out


def _is_compliance_failed(
    doc_type: str,
    compliance_check: dict[str, Any] | None,
) -> bool:
    """When the compliance validator marked this document type
    with status='fail', skip the writeback. Anything else
    (pass, warn, missing) is allowed — warns are still publishable
    with merchant judgement, and a missing entry means the
    validator never inspected this type.
    """
    if not isinstance(compliance_check, dict) or not doc_type:
        return False
    entry = compliance_check.get(doc_type)
    if not isinstance(entry, dict):
        return False
    return str(entry.get("status", "")).lower() == "fail"


def _resolve_handle(doc_type: str, title: str) -> str:
    if doc_type in _HANDLE_DEFAULTS:
        return _HANDLE_DEFAULTS[doc_type]
    return _slugify(doc_type or title)


def _slugify(raw: str) -> str:
    out: list[str] = []
    for ch in raw.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:64]


# ── Router boilerplate ────────────────────────────────────────


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed: %s", exc)
        return None
    try:
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_CREATE_PAGE
