"""Niche-aware Schema.org JSON-LD structured data generator.

JSON-LD blocks injected into a Shopify theme's ``<head>``
tell Google how to render rich results: star ratings on
product cards, FAQ accordions in search, breadcrumb
navigation in the SERP, organisation-level brand presence.

Default Shopify themes ship with the bare-minimum
``Product`` schema. Most stores never add Organisation,
FAQPage, or Article schemas -- which means they ship
without rich-result eligibility.

This module generates the four highest-leverage JSON-LD
blocks per store + niche:

  1. **Organization** -- name, URL, logo, contact -- the
     brand-presence card Google shows on
     "site:[your-domain]" queries.
  2. **FAQPage** -- the same Q&A entries from
     ``support_kb`` re-formatted as Schema.org -- enables
     FAQ rich snippets directly in search results.
  3. **WebSite** with SearchAction -- gets you the
     site-search box in Google.
  4. **BreadcrumbList** for the homepage -- foundational
     breadcrumb schema that themes can extend per page.

Persists as a Shopify page (handle ``structured-data``)
with the JSON-LD blocks in ``<pre>`` for operators to
paste into theme.liquid ``<head>`` -- same pattern as
``homepage_hero`` / ``theme_palette`` / ``email_content``.

Return shape from :func:`generate_structured_data`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "site_url": "https://acme.com",
        "blocks": {
            "organization":   <dict>,
            "website":        <dict>,
            "faqpage":        <dict>,
            "breadcrumblist": <dict>,
        },
    }

Each block is a dict ready to be JSON-serialised + wrapped
in a ``<script type="application/ld+json">`` tag. Records
via Pattern Z.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific seed FAQ entries for the FAQPage block.
# Mirrors a subset of `support_kb._UNIVERSAL_ENTRIES` so the
# two stay consistent without forcing a runtime dependency
# on the KB module. 5 entries is the Google-recommended
# sweet spot for FAQPage rich snippets.
_FAQ_ENTRIES: list[tuple[str, str]] = [
    (
        "How long until my order ships?",
        "Orders typically ship within 1-3 business days "
        "of payment. You'll get a tracking email once "
        "your package leaves the warehouse.",
    ),
    (
        "Do you ship internationally?",
        "Yes, we ship to most countries. International "
        "delivery takes 7-21 business days; customs "
        "delays may apply.",
    ),
    (
        "What's your return policy?",
        "Most items are returnable in original condition. "
        "See our refund policy page for the full terms "
        "by category.",
    ),
    (
        "How can I track my order?",
        "Once your order ships, you'll receive a tracking "
        "link by email. If you can't find it, check your "
        "spam folder before reaching out.",
    ),
    (
        "How do I contact support?",
        "Use the contact form on our site or reply to any "
        "of our emails. We respond within 24 business "
        "hours.",
    ),
]


_SD_PAGE_TITLE: str = "Structured Data"
_SD_PAGE_HANDLE: str = "structured-data"


def generate_structured_data(
    *,
    store_name: str,
    niche: str = "general",
    site_url: str | None = None,
    logo_url: str | None = None,
    support_email: str | None = None,
) -> dict[str, Any]:
    """Build the 4 Schema.org JSON-LD blocks.

    Args:
        store_name: Display name. Empty -> empty dict.
        niche: Lowercase niche key (used for logging /
            metadata; the blocks themselves are
            niche-agnostic, but the recorder tags them).
        site_url: Public URL of the storefront. Required
            for Organization + WebSite blocks. Falls back
            to ``https://{slug}.myshopify.com`` when
            absent.
        logo_url: Optional logo URL for the Organization
            block.
        support_email: Optional support email for the
            Organization contactPoint. Placeholder
            domains rejected; falls back to no
            contactPoint when none is supplied.

    Returns:
        ``{store_name, niche, site_url, blocks: {...}}``.
        Empty dict when ``store_name`` is blank.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    resolved_url = _resolve_site_url(name, site_url)
    safe_email = _sanitize_email(support_email)

    org = _organization_block(
        name=name, site_url=resolved_url,
        logo_url=logo_url,
        support_email=safe_email,
    )
    site = _website_block(name=name, site_url=resolved_url)
    faq = _faqpage_block()
    breadcrumbs = _breadcrumblist_block(site_url=resolved_url)

    return {
        "store_name": name,
        "niche": niche_n,
        "site_url": resolved_url,
        "blocks": {
            "organization": org,
            "website": site,
            "faqpage": faq,
            "breadcrumblist": breadcrumbs,
        },
    }


def _organization_block(
    *,
    name: str,
    site_url: str,
    logo_url: str | None,
    support_email: str | None,
) -> dict[str, Any]:
    org: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": name,
        "url": site_url,
    }
    if logo_url and logo_url.strip():
        org["logo"] = logo_url.strip()
    if support_email:
        org["contactPoint"] = {
            "@type": "ContactPoint",
            "email": support_email,
            "contactType": "customer support",
        }
    return org


def _website_block(
    *, name: str, site_url: str,
) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": name,
        "url": site_url,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": (
                    f"{site_url}/search?q={{search_term_string}}"
                ),
            },
            "query-input": (
                "required name=search_term_string"
            ),
        },
    }


def _faqpage_block() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": a,
                },
            }
            for q, a in _FAQ_ENTRIES
        ],
    }


def _breadcrumblist_block(
    *, site_url: str,
) -> dict[str, Any]:
    """Foundational homepage breadcrumb. Themes extend
    per-page (e.g. collection / product / article) using
    the same `@type` + `itemListElement` shape.
    """
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": site_url,
            },
        ],
    }


def render_structured_data_html(
    spec: dict[str, Any],
) -> str:
    """Render the spec as a Shopify page body.

    For each block, emits a ``<script
    type="application/ld+json">`` tag containing the
    JSON-LD body. Side-by-side, the page is what the
    operator pastes into theme.liquid ``<head>``.

    Empty / non-dict spec -> empty string.
    """
    if not isinstance(spec, dict) or not spec.get("blocks"):
        return ""

    name = html.escape(spec.get("store_name", "") or "")
    blocks = spec.get("blocks") or {}

    sections: list[str] = []
    for label, block in blocks.items():
        if not isinstance(block, dict) or not block:
            continue
        section_label = label.replace("_", " ").title()
        json_str = json.dumps(block, indent=2, sort_keys=False)
        safe_json = html.escape(json_str)
        sections.append(
            "<section class=\"sd-block\">"
            f"<h2>{html.escape(section_label)}</h2>"
            "<pre class=\"sd-json\">"
            "&lt;script type=&quot;application/ld+json&quot;&gt;\n"
            f"{safe_json}\n"
            "&lt;/script&gt;"
            "</pre>"
            "</section>"
        )

    return (
        "<section class=\"structured-data\">"
        f"<h1>{name} -- Structured Data (JSON-LD)</h1>"
        "<p>Paste each <code>&lt;script&gt;</code> block "
        "into your theme's <code>&lt;head&gt;</code>. "
        "Google + other search engines parse these to "
        "render rich results: site-search box, FAQ "
        "snippets, breadcrumbs, brand cards.</p>"
        + "".join(sections) +
        "</section>"
    )


def apply_structured_data(
    spec: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Persist the structured-data spec as a Shopify page.

    Args:
        spec: Dict from :func:`generate_structured_data`.
        store_id: Optional per-store recording scope.

    Returns:
        ``{applied, handle, error}``.
    """
    if not isinstance(spec, dict) or not spec.get("blocks"):
        return {
            "applied": False,
            "handle": _SD_PAGE_HANDLE,
            "error": "no_structured_data_spec",
        }

    body_html = render_structured_data_html(spec)
    if not body_html:
        _record(
            success=False, store_id=store_id,
            error="empty_render", spec=spec,
        )
        return {
            "applied": False,
            "handle": _SD_PAGE_HANDLE,
            "error": "empty_render",
        }

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        _record(
            success=False, store_id=store_id,
            error="router_unavailable", spec=spec,
        )
        return {
            "applied": False,
            "handle": _SD_PAGE_HANDLE,
            "error": "router_unavailable",
        }

    params = {
        "title": _SD_PAGE_TITLE,
        "handle": _SD_PAGE_HANDLE,
        "body_html": body_html,
        "published": True,
    }
    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "structured_data router.execute raised: %s",
            exc,
        )
        _record(
            success=False, store_id=store_id,
            error=str(exc), spec=spec,
        )
        return {
            "applied": False,
            "handle": _SD_PAGE_HANDLE,
            "error": f"adapter_raise: {exc}",
        }

    ok = bool(getattr(result, "ok", False))
    error = getattr(result, "error", None)
    _record(
        success=ok, store_id=store_id,
        error=None if ok else str(error or "rejected"),
        spec=spec,
    )
    if ok:
        return {
            "applied": True,
            "handle": _SD_PAGE_HANDLE,
            "error": None,
        }
    return {
        "applied": False,
        "handle": _SD_PAGE_HANDLE,
        "error": str(error or "rejected"),
    }


# ── Helpers ───────────────────────────────────────────────────


_PLACEHOLDER_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net",
    "test.com", "localhost", "invalid",
})


def _sanitize_email(value: str | None) -> str | None:
    """Reject placeholder domains -- mirrors the page_generator
    / policy_generator pattern."""
    raw = (value or "").strip()
    if not raw or "@" not in raw:
        return None
    domain = raw.rsplit("@", 1)[-1].lower()
    if domain in _PLACEHOLDER_DOMAINS:
        return None
    return raw


def _resolve_site_url(
    store_name: str, site_url: str | None,
) -> str:
    """Use the supplied URL if present + valid; otherwise
    fall back to a deterministic
    ``https://<slug>.myshopify.com`` so the JSON-LD blocks
    are still well-formed."""
    raw = (site_url or "").strip()
    if raw.startswith(("http://", "https://")):
        return raw.rstrip("/")
    slug = "".join(
        ch if ch.isalnum() else "-"
        for ch in store_name.lower()
    ).strip("-")
    slug = slug or "store"
    # Collapse runs of hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"https://{slug}.myshopify.com"


def _record(
    *,
    success: bool,
    store_id: str | None,
    error: str | None,
    spec: dict[str, Any],
) -> None:
    blocks = spec.get("blocks") or {}
    params: dict[str, Any] = {
        "handle": _SD_PAGE_HANDLE,
        "block_keys": sorted(blocks.keys()),
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_structured_data",
            capability="SHOPIFY_CREATE_PAGE",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "handle": _SD_PAGE_HANDLE,
                "block_count": len(blocks),
                "niche": spec.get("niche", ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "structured_data record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "structured_data router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PAGE
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "structured_data capability resolve failed: %s",
            exc,
        )
        return None
