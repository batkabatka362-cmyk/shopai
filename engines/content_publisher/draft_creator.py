"""W963-6: content_publisher draft article creator.

Enqueues blog post candidates as pending Shopify DRAFT articles
via the approval queue. Operator approves → executor fires
SHOPIFY_CREATE_ARTICLE with is_published=False.

Mirrors engines/product_sourcer/draft_creator.py shape so the
dispatcher patterns stay symmetric.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


_ENGINE = "content_publisher"
_ACTION_TYPE = "create_draft_article"
_CAPABILITY = "SHOPIFY_CREATE_ARTICLE"


def _candidate_to_params(
    candidate: dict[str, Any], *, niche: str,
    blog_id: str | None,
) -> dict[str, Any]:
    """Translate a serialized BlogCandidate into the friendly
    call shape SHOPIFY_CREATE_ARTICLE expects."""
    title = str(candidate.get("title") or "").strip()
    body = str(candidate.get("body_html") or "").strip()
    excerpt = str(candidate.get("meta_excerpt") or "").strip()
    keyword = str(candidate.get("keyword") or "").strip()
    tags = candidate.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    params: dict[str, Any] = {
        "title": title,
        "body_html": body,
        "author_name": "ShopAI Editorial",
        "tags": [t for t in tags if isinstance(t, str) and t],
        # is_published=False keeps the article DRAFT until
        # operator publishes via Shopify Admin OR a future
        # --publish flag.
        "is_published": False,
        # W963-6: structured metadata for source-tracking.
        "_metadata": {
            "source": "content_publisher",
            "niche": niche,
            "keyword": keyword,
            "meta_excerpt": excerpt,
        },
    }
    if blog_id:
        params["blog_id"] = str(blog_id)
    return params


def _build_narrative(
    candidate: dict[str, Any], niche: str,
) -> str:
    title = candidate.get("title") or "(untitled)"
    kw = candidate.get("keyword") or "(no keyword)"
    return (
        f"Create DRAFT article '{title}' "
        f"(niche={niche}, target keyword: {kw})"
    )


def enqueue_articles_for_approval(
    candidates: list[dict[str, Any]], *, niche: str,
    blog_id: str | None = None,
) -> list[dict[str, Any]]:
    """Enqueue every candidate as a pending DRAFT-article
    creation. Returns one entry per successfully-enqueued
    candidate (or empty list when blog_id is missing / queue
    unavailable).
    """
    if not isinstance(candidates, list):
        return []
    if not blog_id:
        # Shopify requires a parent blog_id. Without one, we
        # can't enqueue anything that the executor could
        # actually replay. Surface the gap to the operator.
        logger.debug(
            "content_publisher: no blog_id supplied, "
            "skipping enqueue",
        )
        return []

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "content_publisher: approval queue import failed: %s",
            exc,
        )
        return []

    out: list[dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict) or not cand.get("title"):
            continue
        params = _candidate_to_params(
            cand, niche=niche, blog_id=blog_id,
        )
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
                "content_publisher: enqueue raised "
                "for '%s': %s", cand.get("title"), exc,
            )
            continue
        out.append({
            "pending_action_id": action.id,
            "narrative": narrative,
            "params": params,
        })
    return out
