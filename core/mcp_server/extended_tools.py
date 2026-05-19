"""Extended ShopAI MCP tools for queued niche-aware modules.

PR #399 (the base MCP server) shipped tool wrappers for the
on-main modules (collections, pages, policies, audit).
This module adds wrappers for the 16 queued niche-aware
modules (#379-#398).

Each tool follows the same lazy-import pattern as
``tools.py``: if the underlying engine module isn't yet
on main, the tool returns a clean error envelope. As the
queued PRs land, the corresponding tools automatically
start working -- no MCP server redeploy needed.

Tools added:

  Content recommendations (read-only):
    recommend_homepage_hero
    recommend_theme_palette
    recommend_support_kb
    recommend_email_templates
    recommend_blog_starter
    recommend_coupon_playbook
    recommend_structured_data
    recommend_customer_segments
    recommend_loyalty_tiers
    recommend_announcement_bar
    recommend_metaobject_definitions
    recommend_review_email
    recommend_winback_email
    recommend_homepage_sections
    recommend_newsletter_popup
    recommend_cross_sell_rules
    recommend_welcome_discount
    recommend_tag_library
    recommend_smart_collections

  Apply (writes to Shopify):
    apply_homepage_hero
    apply_theme_palette
    apply_support_kb
    apply_email_templates
    apply_blog_starter
    apply_structured_data
    apply_customer_segments
    apply_announcement_bar
    apply_metaobject_definitions
    apply_review_email
    apply_winback_email
    apply_homepage_sections
    apply_newsletter_popup
    apply_cross_sell_rules
    apply_smart_collections

The recommend/apply asymmetry: some modules are pure
content references (coupon_playbook, loyalty_tiers,
tag_library) -- they generate specs operators consume
elsewhere, no direct Shopify write path.
"""
from __future__ import annotations

import logging
from typing import Any

from .tools import (
    _err,
    _ok,
    _validate_niche,
    _validate_store_name,
)

logger = logging.getLogger(__name__)


def _lazy_call(
    module_path: str,
    func_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Import + call an engine function lazily.

    Returns ``_ok(result)`` on success, ``_err(...)`` on
    any failure (import error, raise, etc.).
    """
    try:
        mod = __import__(
            module_path, fromlist=[func_name],
        )
        fn = getattr(mod, func_name)
    except Exception as exc:  # noqa: BLE001
        return _err(
            f"engine_unavailable: {module_path}."
            f"{func_name} ({exc})"
        )
    try:
        return _ok(fn(**kwargs))
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_raised: {exc}")


# ── recommend_* tools (content) ──────────────────────────────


def recommend_homepage_hero(
    *,
    store_name: str,
    niche: str = "general",
    primary_cta_url: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Recommend niche-aware homepage hero content."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if primary_cta_url:
        kwargs["primary_cta_url"] = primary_cta_url
    if image_url:
        kwargs["image_url"] = image_url
    return _lazy_call(
        "engines.store_setup.homepage_hero",
        "generate_hero",
        **kwargs,
    )


def recommend_theme_palette(
    *, niche: str = "general",
) -> dict[str, Any]:
    """Recommend a WCAG-compliant niche-aware palette."""
    return _lazy_call(
        "engines.store_setup.theme_palette",
        "generate_palette",
        niche=_validate_niche(niche),
    )


def recommend_support_kb(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend the customer-support Q&A knowledge base."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.support_kb",
        "generate_support_kb",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_email_templates(
    *,
    store_name: str,
    niche: str = "general",
    welcome_discount_code: str | None = None,
    welcome_discount_pct: int | None = None,
) -> dict[str, Any]:
    """Recommend welcome + abandoned-cart email templates."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if welcome_discount_code:
        kwargs["welcome_discount_code"] = welcome_discount_code
    if welcome_discount_pct is not None:
        kwargs["welcome_discount_pct"] = int(
            welcome_discount_pct,
        )
    return _lazy_call(
        "engines.store_setup.email_content",
        "generate_emails",
        **kwargs,
    )


def recommend_blog_starter(
    *,
    store_name: str,
    niche: str = "general",
    author_name: str | None = None,
) -> dict[str, Any]:
    """Recommend 3 niche-aware blog post drafts."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if author_name:
        kwargs["author_name"] = author_name
    return _lazy_call(
        "engines.store_setup.blog_starter",
        "generate_blog_starter",
        **kwargs,
    )


def recommend_coupon_playbook(
    *,
    store_name: str,
    niche: str = "general",
    days_valid: int = 365,
) -> dict[str, Any]:
    """Recommend the 6 evergreen discount specs (free
    shipping / bundle / loyalty / subscriber / cart
    recovery / seasonal)."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.coupon_playbook",
        "generate_playbook",
        store_name=name,
        niche=_validate_niche(niche),
        days_valid=int(days_valid),
    )


def recommend_structured_data(
    *,
    store_name: str,
    niche: str = "general",
    site_url: str | None = None,
    logo_url: str | None = None,
    support_email: str | None = None,
) -> dict[str, Any]:
    """Recommend Schema.org JSON-LD blocks (Organization,
    WebSite, FAQPage, BreadcrumbList)."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if site_url:
        kwargs["site_url"] = site_url
    if logo_url:
        kwargs["logo_url"] = logo_url
    if support_email:
        kwargs["support_email"] = support_email
    return _lazy_call(
        "engines.store_setup.structured_data",
        "generate_structured_data",
        **kwargs,
    )


def recommend_customer_segments(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend the 7+ universal customer segments."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.customer_segments",
        "generate_segment_pack",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_loyalty_tiers(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend niche-tuned bronze/silver/gold/platinum
    tier thresholds + points-per-dollar rate."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.loyalty_tiers",
        "generate_tier_template",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_announcement_bar(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend top-of-page sticky banner options."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.announcement_bar",
        "generate_announcement_bars",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_metaobject_definitions(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend niche-aware metaobject definitions."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.metaobject_definitions",
        "generate_metaobject_pack",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_review_email(
    *,
    store_name: str,
    niche: str = "general",
    incentive_code: str | None = None,
    incentive_pct: int | None = None,
) -> dict[str, Any]:
    """Recommend post-purchase review request email
    templates."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if incentive_code:
        kwargs["incentive_code"] = incentive_code
    if incentive_pct is not None:
        kwargs["incentive_pct"] = int(incentive_pct)
    return _lazy_call(
        "engines.store_setup.review_request_email",
        "generate_review_request_emails",
        **kwargs,
    )


def recommend_winback_email(
    *,
    store_name: str,
    niche: str = "general",
    incentive_code: str | None = None,
    incentive_pct: int | None = None,
) -> dict[str, Any]:
    """Recommend 3-step win-back email sequence for
    lapsed customers."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if incentive_code:
        kwargs["incentive_code"] = incentive_code
    if incentive_pct is not None:
        kwargs["incentive_pct"] = int(incentive_pct)
    return _lazy_call(
        "engines.store_setup.winback_email",
        "generate_winback_sequence",
        **kwargs,
    )


def recommend_homepage_sections(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend niche-aware homepage section ordering."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.homepage_sections",
        "recommend_homepage_sections",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_newsletter_popup(
    *,
    store_name: str,
    niche: str = "general",
    discount_code: str | None = None,
    discount_pct: int | None = None,
) -> dict[str, Any]:
    """Recommend newsletter signup popup content
    (first-visit + exit-intent variants)."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
    }
    if discount_code:
        kwargs["discount_code"] = discount_code
    if discount_pct is not None:
        kwargs["discount_pct"] = int(discount_pct)
    return _lazy_call(
        "engines.store_setup.newsletter_popup",
        "generate_newsletter_popups",
        **kwargs,
    )


def recommend_cross_sell_rules(
    *, store_name: str, niche: str = "general",
) -> dict[str, Any]:
    """Recommend niche-aware cross-sell + upsell rule
    templates."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _lazy_call(
        "engines.store_setup.cross_sell_rules",
        "generate_cross_sell_rules",
        store_name=name,
        niche=_validate_niche(niche),
    )


def recommend_welcome_discount(
    *,
    store_name: str,
    niche: str = "general",
    code: str | None = None,
    days_valid: int = 60,
) -> dict[str, Any]:
    """Recommend launch-time WELCOME{N} discount params."""
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    kwargs: dict[str, Any] = {
        "store_name": name,
        "niche": _validate_niche(niche),
        "days_valid": int(days_valid),
    }
    if code:
        kwargs["code"] = code
    return _lazy_call(
        "engines.store_setup.welcome_discount",
        "generate_welcome_discount",
        **kwargs,
    )


def recommend_tag_library(
    *, niche: str = "general",
) -> dict[str, Any]:
    """Return the niche's canonical tag taxonomy."""
    return _lazy_call(
        "engines.store_setup.tag_library",
        "get_niche_tags",
        niche=_validate_niche(niche),
    )


def recommend_smart_collections(
    *, niche: str = "general",
) -> dict[str, Any]:
    """Recommend rule-driven smart collection specs."""
    return _lazy_call(
        "engines.store_setup.smart_collection_rules",
        "generate_smart_collections",
        niche=_validate_niche(niche),
    )


# ── apply_* tools (writes) ──────────────────────────────────


def _apply_via(
    module_path: str,
    gen_name: str,
    apply_name: str,
    gen_kwargs: dict[str, Any],
    store_id: str | None,
) -> dict[str, Any]:
    """Generate spec then apply -- the standard pattern."""
    try:
        mod = __import__(
            module_path, fromlist=[gen_name, apply_name],
        )
        gen = getattr(mod, gen_name)
        apply = getattr(mod, apply_name)
    except Exception as exc:  # noqa: BLE001
        return _err(
            f"engine_unavailable: {module_path} ({exc})"
        )
    try:
        spec = gen(**gen_kwargs)
        result = apply(spec, store_id=store_id)
    except Exception as exc:  # noqa: BLE001
        return _err(f"applier_raised: {exc}")
    return _ok(result)


def apply_homepage_hero(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.homepage_hero",
        "generate_hero",
        "apply_hero",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_theme_palette(
    *, niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    return _apply_via(
        "engines.store_setup.theme_palette",
        "generate_palette",
        "apply_palette",
        {"niche": _validate_niche(niche)},
        store_id,
    )


def apply_support_kb(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.support_kb",
        "generate_support_kb",
        "apply_support_kb",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_email_templates(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.email_content",
        "generate_emails",
        "apply_emails",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_blog_starter(
    *,
    store_name: str,
    niche: str = "general",
    blog_id: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    try:
        mod = __import__(
            "engines.store_setup.blog_starter",
            fromlist=[
                "generate_blog_starter",
                "apply_blog_starter",
            ],
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_unavailable: {exc}")
    try:
        spec = mod.generate_blog_starter(
            store_name=name,
            niche=_validate_niche(niche),
        )
        kw = {"store_id": store_id}
        if blog_id:
            kw["blog_id"] = blog_id
        result = mod.apply_blog_starter(spec, **kw)
    except Exception as exc:  # noqa: BLE001
        return _err(f"applier_raised: {exc}")
    return _ok(result)


def apply_structured_data(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.structured_data",
        "generate_structured_data",
        "apply_structured_data",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_customer_segments(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.customer_segments",
        "generate_segment_pack",
        "apply_segment_pack",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_announcement_bar(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.announcement_bar",
        "generate_announcement_bars",
        "apply_bars",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_metaobject_definitions(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.metaobject_definitions",
        "generate_metaobject_pack",
        "apply_metaobject_pack",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_review_email(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.review_request_email",
        "generate_review_request_emails",
        "apply_review_emails",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_winback_email(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.winback_email",
        "generate_winback_sequence",
        "apply_winback",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_homepage_sections(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.homepage_sections",
        "recommend_homepage_sections",
        "apply_sections",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_newsletter_popup(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.newsletter_popup",
        "generate_newsletter_popups",
        "apply_popups",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_cross_sell_rules(
    *,
    store_name: str,
    niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    name = _validate_store_name(store_name)
    if not name:
        return _err("store_name_required")
    return _apply_via(
        "engines.store_setup.cross_sell_rules",
        "generate_cross_sell_rules",
        "apply_rules",
        {"store_name": name, "niche": _validate_niche(niche)},
        store_id,
    )


def apply_smart_collections(
    *, niche: str = "general",
    store_id: str | None = None,
) -> dict[str, Any]:
    """Smart collections reuse the collection_seeder
    applier. Generate the spec via
    smart_collection_rules then push via the existing
    apply_starter_collections."""
    try:
        from engines.store_setup.smart_collection_rules import (
            generate_smart_collections,
        )
        from engines.store_setup.collection_seeder import (
            apply_starter_collections,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"engine_unavailable: {exc}")
    try:
        spec = generate_smart_collections(
            niche=_validate_niche(niche),
        )
        result = apply_starter_collections(
            spec["collections"],
            store_id=store_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"applier_raised: {exc}")
    return _ok(result)


# ── Extended registry ────────────────────────────────────────


EXTENDED_TOOLS: list[tuple[str, Any, str]] = [
    # Content recommendations
    (
        "recommend_homepage_hero",
        recommend_homepage_hero,
        "Recommend niche-aware homepage hero content "
        "(headline + subhead + CTAs).",
    ),
    (
        "recommend_theme_palette",
        recommend_theme_palette,
        "Recommend a WCAG AA-compliant niche-aware "
        "6-token palette.",
    ),
    (
        "recommend_support_kb",
        recommend_support_kb,
        "Recommend the customer-support Q&A knowledge "
        "base (10-12 entries).",
    ),
    (
        "recommend_email_templates",
        recommend_email_templates,
        "Recommend welcome + abandoned-cart email "
        "templates.",
    ),
    (
        "recommend_blog_starter",
        recommend_blog_starter,
        "Recommend 3 niche-aware blog post drafts.",
    ),
    (
        "recommend_coupon_playbook",
        recommend_coupon_playbook,
        "Recommend the 6 evergreen discount specs "
        "(free shipping / bundle / loyalty / subscriber "
        "/ cart recovery / seasonal).",
    ),
    (
        "recommend_structured_data",
        recommend_structured_data,
        "Recommend Schema.org JSON-LD blocks for SEO "
        "rich results.",
    ),
    (
        "recommend_customer_segments",
        recommend_customer_segments,
        "Recommend the 7+ universal customer segments + "
        "niche-specific ones.",
    ),
    (
        "recommend_loyalty_tiers",
        recommend_loyalty_tiers,
        "Recommend niche-tuned loyalty tier thresholds.",
    ),
    (
        "recommend_announcement_bar",
        recommend_announcement_bar,
        "Recommend top-of-page sticky banner options.",
    ),
    (
        "recommend_metaobject_definitions",
        recommend_metaobject_definitions,
        "Recommend niche-aware Shopify metaobject "
        "type definitions.",
    ),
    (
        "recommend_review_email",
        recommend_review_email,
        "Recommend post-purchase review request email "
        "templates.",
    ),
    (
        "recommend_winback_email",
        recommend_winback_email,
        "Recommend 3-step lapsed-customer win-back "
        "email sequence.",
    ),
    (
        "recommend_homepage_sections",
        recommend_homepage_sections,
        "Recommend niche-aware homepage section ordering.",
    ),
    (
        "recommend_newsletter_popup",
        recommend_newsletter_popup,
        "Recommend newsletter signup popup content "
        "(first-visit + exit-intent).",
    ),
    (
        "recommend_cross_sell_rules",
        recommend_cross_sell_rules,
        "Recommend niche-aware cross-sell + upsell "
        "rule templates.",
    ),
    (
        "recommend_welcome_discount",
        recommend_welcome_discount,
        "Recommend launch-time WELCOME{N} discount "
        "params.",
    ),
    (
        "recommend_tag_library",
        recommend_tag_library,
        "Return the canonical tag taxonomy for a niche.",
    ),
    (
        "recommend_smart_collections",
        recommend_smart_collections,
        "Recommend rule-driven smart collection specs.",
    ),
    # Apply tools
    (
        "apply_homepage_hero",
        apply_homepage_hero,
        "Push homepage hero content to Shopify.",
    ),
    (
        "apply_theme_palette",
        apply_theme_palette,
        "Push theme palette spec to Shopify.",
    ),
    (
        "apply_support_kb",
        apply_support_kb,
        "Push customer-support knowledge base page to "
        "Shopify.",
    ),
    (
        "apply_email_templates",
        apply_email_templates,
        "Push email templates reference page to "
        "Shopify.",
    ),
    (
        "apply_blog_starter",
        apply_blog_starter,
        "Push 3 blog articles to Shopify "
        "(auto-creates blog if needed).",
    ),
    (
        "apply_structured_data",
        apply_structured_data,
        "Push Schema.org JSON-LD reference page to "
        "Shopify.",
    ),
    (
        "apply_customer_segments",
        apply_customer_segments,
        "Push customer segments to Shopify via "
        "SHOPIFY_CREATE_SEGMENT.",
    ),
    (
        "apply_announcement_bar",
        apply_announcement_bar,
        "Push announcement bar options page to Shopify.",
    ),
    (
        "apply_metaobject_definitions",
        apply_metaobject_definitions,
        "Push metaobject definitions to Shopify via "
        "SHOPIFY_CREATE_METAOBJECT_DEFINITION.",
    ),
    (
        "apply_review_email",
        apply_review_email,
        "Push review-request email page to Shopify.",
    ),
    (
        "apply_winback_email",
        apply_winback_email,
        "Push win-back email sequence page to Shopify.",
    ),
    (
        "apply_homepage_sections",
        apply_homepage_sections,
        "Push homepage section ordering page to Shopify.",
    ),
    (
        "apply_newsletter_popup",
        apply_newsletter_popup,
        "Push newsletter popup content page to Shopify.",
    ),
    (
        "apply_cross_sell_rules",
        apply_cross_sell_rules,
        "Push cross-sell rules reference page to "
        "Shopify.",
    ),
    (
        "apply_smart_collections",
        apply_smart_collections,
        "Push smart (rule-driven) collections to "
        "Shopify.",
    ),
]
