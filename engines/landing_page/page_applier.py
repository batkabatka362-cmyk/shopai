"""Landing Page Engine — Shopify page applier.

The landing_page engine emits a list of variant pages
(headline / subheadline / hero / benefits / cta / social proof)
along with a ``best_variant`` index pointing at the highest-scoring
copy. Pre-fix that copy lived only in the engine output — the
merchant had to manually paste each section into a Shopify page
template before launching the campaign.

This applier closes the loop. When opt-in is set and the
guardrails clear, take ``pages[best_variant]``, render it into a
self-contained HTML body, and create an UNPUBLISHED Shopify page
via SHOPIFY_CREATE_PAGE. The merchant reviews the staged page in
admin, attaches a theme template suffix if desired, then publishes
when ready.

UNPUBLISHED-by-default (``is_published=False``) because:
  * Auto-publishing would expose unvetted AI copy to live traffic.
  * The merchant typically wants to attach a campaign-specific
    template suffix that ShopAI can't pick blindly.
  * Same risk gradient as bundle's DRAFT product — staged is the
    safer default.

Two opt-in modes match the established Phase 6/7 pattern:

  data.apply_landing_page=True + data.require_approval=False
    → SHOPIFY_CREATE_PAGE immediately
  data.apply_landing_page=True + data.require_approval=True
    → enqueue to core.approval; merchant approves before the
      mutation lands

Skipped (no API call / no queue entry) when:
  * No pages were generated (engine output empty).
  * best_variant is out of range for the pages list.
  * The picked page has a blank headline (rendering would
    produce a near-empty Shopify page).
  * Router unavailable / adapter rejects (direct path).
  * Approval queue unavailable (approval path).
"""
from __future__ import annotations

import html
from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.landing_page.applier")


def apply_landing_page(
    pages: list[dict[str, Any]],
    best_variant: int,
    estimated_conversion: float,
    *,
    campaign: dict[str, Any] | None = None,
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Create an unpublished Shopify page for the best variant.

    Args:
        pages: List of variant page dicts from the engine.
        best_variant: Index of the highest-scoring variant.
        estimated_conversion: 0-1 expected conversion rate (used
            in recorder telemetry).
        campaign: Optional campaign dict carrying ``name`` /
            ``slug`` (used to seed page title / handle).
        store: Optional config — currently unused, reserved.

    Returns:
        ``{"applied", "page_id", "title", "handle",
        "is_published", "best_variant", "error"}``
        on success or structured skip; ``None`` only when the
        upfront guardrails reject before any router work.
    """
    proposal = _build_proposal(pages, best_variant, campaign)
    if proposal is None:
        return None

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        return {
            "applied": False,
            "page_id": "",
            "title": proposal["title"],
            "handle": proposal["handle"],
            "is_published": False,
            "best_variant": best_variant,
            "error": "router_unavailable",
        }

    recorder_params = {
        "title": proposal["title"],
        "handle": proposal["handle"],
        "best_variant": best_variant,
        "estimated_conversion": estimated_conversion,
    }
    try:
        result = router.execute(capability, proposal["adapter_params"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("apply_landing_page raised: %s", exc)
        record_writeback(
            engine="landing_page",
            action_type="apply_landing_page",
            capability="SHOPIFY_CREATE_PAGE",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return {
            "applied": False,
            "page_id": "",
            "title": proposal["title"],
            "handle": proposal["handle"],
            "is_published": False,
            "best_variant": best_variant,
            "error": f"adapter_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        record_writeback(
            engine="landing_page",
            action_type="apply_landing_page",
            capability="SHOPIFY_CREATE_PAGE",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return {
            "applied": False,
            "page_id": "",
            "title": proposal["title"],
            "handle": proposal["handle"],
            "is_published": False,
            "best_variant": best_variant,
            "error": f"adapter_failed: {err}",
        }

    data = getattr(result, "data", {}) or {}
    page = data.get("page") or {}
    record_writeback(
        engine="landing_page",
        action_type="apply_landing_page",
        capability="SHOPIFY_CREATE_PAGE",
        params=recorder_params,
        success=True,
    )
    return {
        "applied": True,
        "page_id": page.get("id", "") or "",
        "title": page.get("title", proposal["title"]),
        "handle": page.get("handle", proposal["handle"]),
        "is_published": bool(page.get("is_published", False)),
        "best_variant": best_variant,
        "error": None,
    }


def enqueue_landing_page_for_approval(
    pages: list[dict[str, Any]],
    best_variant: int,
    estimated_conversion: float,
    *,
    campaign: dict[str, Any] | None = None,
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park the landing-page proposal in the approval queue.

    Same upfront guards as :func:`apply_landing_page`. Returns
    the standard ``{pending_action_id, narrative, params}`` shape
    used across Phase 6/7 enqueue helpers; ``None`` on guardrail
    rejection or queue failure.
    """
    proposal = _build_proposal(pages, best_variant, campaign)
    if proposal is None:
        return None

    narrative = (
        f"Create staged landing page '{proposal['title']}' "
        f"(handle: {proposal['handle']}, "
        f"~{estimated_conversion*100:.1f}% est. conversion, "
        f"variant #{best_variant})"
    )
    params = {
        "title": proposal["title"],
        "handle": proposal["handle"],
        "best_variant": best_variant,
        "estimated_conversion": estimated_conversion,
        "adapter_params": proposal["adapter_params"],
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="landing_page",
            action_type="apply_landing_page",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            narrative=narrative,
        )
    except Exception:  # noqa: BLE001
        return None

    return {
        "pending_action_id": action.id,
        "narrative": narrative,
        "params": params,
    }


# ── Proposal builder ──────────────────────────────────────────


def _build_proposal(
    pages: list[dict[str, Any]] | None,
    best_variant: int,
    campaign: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate inputs and assemble the adapter-ready proposal.

    Returns ``None`` when any guardrail rejects (no pages,
    out-of-range variant index, blank headline on the picked
    page).
    """
    if not isinstance(pages, list) or not pages:
        return None

    idx = _safe_int(best_variant)
    if idx is None or idx < 0 or idx >= len(pages):
        return None

    page = pages[idx]
    if not isinstance(page, dict):
        return None

    headline = str(page.get("headline", "")).strip()
    if not headline:
        return None

    title = _build_title(headline, campaign)
    handle = _build_handle(title, campaign)
    body_html = _build_body(page)

    adapter_params: dict[str, Any] = {
        "title": title,
        "body_html": body_html,
        "is_published": False,
    }
    if handle:
        adapter_params["handle"] = handle

    return {
        "title": title,
        "handle": handle,
        "body_html": body_html,
        "adapter_params": adapter_params,
    }


def _build_title(headline: str, campaign: dict[str, Any] | None) -> str:
    """Page title prefers the campaign name (operator-facing)
    falling back to the headline."""
    if isinstance(campaign, dict):
        name = str(campaign.get("name", "")).strip()
        if name:
            return name[:200]
    return headline[:200]


def _build_handle(title: str, campaign: dict[str, Any] | None) -> str:
    """URL slug — prefers ``campaign.slug``, falls back to a
    derived slug from the title. Returns blank if neither
    yields a usable slug (the adapter will auto-generate one).
    """
    if isinstance(campaign, dict):
        slug = str(campaign.get("slug", "")).strip()
        if slug:
            return _slugify(slug)
    return _slugify(title)


def _slugify(raw: str) -> str:
    out: list[str] = []
    for ch in raw.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:64]


def _build_body(page: dict[str, Any]) -> str:
    """Render the page sections into a self-contained HTML body.

    HTML-escapes every textual field so engine-generated copy
    can't inject markup unintentionally.
    """
    headline = html.escape(str(page.get("headline", "")).strip())
    subheadline = html.escape(str(page.get("subheadline", "")).strip())
    hero = html.escape(str(page.get("hero_section", "")).strip())
    cta = html.escape(str(page.get("cta", "")).strip())
    social = html.escape(str(page.get("social_proof", "")).strip())
    benefits_raw = page.get("benefits") or []
    benefits = (
        [html.escape(str(b)) for b in benefits_raw if str(b).strip()]
        if isinstance(benefits_raw, list) else []
    )

    parts: list[str] = []
    if headline:
        parts.append(f"<h1>{headline}</h1>")
    if subheadline:
        parts.append(f"<h2>{subheadline}</h2>")
    if hero:
        parts.append(f"<p>{hero}</p>")
    if benefits:
        items = "".join(f"<li>{b}</li>" for b in benefits)
        parts.append(f"<ul>{items}</ul>")
    if cta:
        parts.append(f"<p><strong>{cta}</strong></p>")
    if social:
        parts.append(f'<p><em>{social}</em></p>')
    return "\n".join(parts)


def _safe_int(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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
