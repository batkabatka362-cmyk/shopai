"""Canonical ShopAI Shopify scope list — one source of truth.

Every other module that needs scope strings imports from here.
Drift between the OAuth redirect (core/auth/shopify_auth.py),
the owner-facing audit script (scripts/deguar_scope_audit.py),
and the shopify_admin resource implementations caused the
"route works in dev, 403s in prod" issue we hit around
commit 7fe79a8 — moving everything behind this module + a
regression test keeps the three in lock-step.

Scope naming follows Shopify's documented handles. Unlike the
legacy audit list (18 scopes), this one reflects every resource
we implemented across waves 1-5:

  Wave 1  — discounts, inventory, draft orders, client
  Wave 2  — fulfillments, refunds, customers
  Wave 3a — orders, products unified
  Wave 3b — themes, shipping zones/rates, carrier services
  Wave 4a — gift cards
  Wave 4b — collections unification
  Wave 4c — markets (GraphQL)
  Wave 4d — marketing events
  Wave 4e — blogs + articles + pages
  Wave 5a — shop + locales + currencies + access scopes
  Wave 5b — order risks + disputes
  Wave 5c — fulfillment services + events
  Wave 5d — customer metafields + segments + saved searches
  Wave 5e — automatic discounts + article comments
  Wave 5f — bulk ops + reports + payouts + tax rates + users

Each scope has three annotations:
  * ``tier``  — required / recommended / plus-only
  * ``why``   — owner-facing copy ("without this X breaks")
  * ``waves`` — which shipped waves depend on this scope

Never gate a write path on a `recommended` scope — the
OAuth flow should succeed even if a `recommended` scope is
denied. Use ``required_scopes()`` to get the must-have
subset for the install URL and ``all_scopes()`` for the
optional-include superset.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable


@dataclasses.dataclass(frozen=True)
class Scope:
    handle: str
    tier: str          # "required" | "recommended" | "plus_only"
    why: str
    waves: tuple[str, ...]


# ── Reads ─────────────────────────────────────────────────


_READS: tuple[Scope, ...] = (
    Scope(
        "read_products", "required",
        "catalog fetch, analytics, variants, images, "
        "metafield definitions, collections",
        ("1", "3a", "4b"),
    ),
    Scope(
        "read_orders", "required",
        "order webhook → learning loop; refunds list; "
        "order risks read",
        ("2", "3a", "5b"),
    ),
    Scope(
        "read_all_orders", "required",
        "order history >60 days — without it the brain "
        "can only see the last 60d of signal",
        ("2", "3a"),
    ),
    Scope(
        "read_customers", "required",
        "segmentation, retention, saved searches, "
        "metafields, segments (GraphQL)",
        ("2", "5d"),
    ),
    Scope(
        "read_inventory", "required",
        "stock signal for sourcing + supplier sync",
        ("1",),
    ),
    Scope(
        "read_locations", "required",
        "location list (wave 1 inventory)",
        ("1",),
    ),
    Scope(
        "read_draft_orders", "required",
        "full draft-order lifecycle read",
        ("1",),
    ),
    Scope(
        "read_fulfillments", "required",
        "fulfillment orders + fulfillments + services "
        "+ events read",
        ("2", "5c"),
    ),
    Scope(
        "read_content", "required",
        "blogs / articles / pages / article comments",
        ("4e", "5e"),
    ),
    Scope(
        "read_online_store_pages", "required",
        "narrower pages-only read complementing "
        "read_content; Shopify requires both for page CRUD "
        "on 2024+ API versions",
        ("4e",),
    ),
    Scope(
        "read_files", "required",
        "stagedUploadsCreate target read + product image "
        "lookup; wave 3a image upload + wave 3b theme asset "
        "upsert both require this",
        ("3a", "3b"),
    ),
    Scope(
        "read_themes", "required",
        "theme + theme assets read",
        ("3b",),
    ),
    Scope(
        "read_script_tags", "required",
        "read currently-installed tracking pixels",
        ("store_configurator",),
    ),
    Scope(
        "read_price_rules", "required",
        "discount audit, coupon inventory",
        ("1",),
    ),
    Scope(
        "read_discounts", "required",
        "new-format discount code read + automatic "
        "discounts (wave 5e)",
        ("1", "5e"),
    ),
    Scope(
        "read_gift_cards", "required",
        "gift card list / get / count / search (wave 4a)",
        ("4a",),
    ),
    Scope(
        "read_shipping", "required",
        "shipping zones + rates + carrier services + "
        "tax rates read",
        ("3b", "5f"),
    ),
    Scope(
        "read_marketing_events", "recommended",
        "external campaign attribution events (wave 4d)",
        ("4d",),
    ),
    Scope(
        "read_markets", "recommended",
        "Shopify Markets list / get (wave 4c)",
        ("4c",),
    ),
    Scope(
        "read_locales", "recommended",
        "shop locales + presentment currencies (wave 5a). "
        "Shopify 2024+ merges this into read_translations; "
        "grant whichever the store UI exposes.",
        ("5a",),
    ),
    Scope(
        "read_translations", "recommended",
        "2024+ replacement name for read_locales; required "
        "for shopLocales + Translation API reads (wave 5a)",
        ("5a",),
    ),
    Scope(
        "read_metaobjects", "recommended",
        "brand-kit / testimonial / custom-object reads — "
        "Shopify's 2024+ flexible custom-data type the "
        "content engines use for structured brand blocks",
        ("4e", "5d"),
    ),
    Scope(
        "read_pixels", "recommended",
        "web pixels extension (2024+). Replaces some "
        "script_tags use for conversion tracking. Read side "
        "lets the brain know which pixels are active.",
        ("store_configurator",),
    ),
    Scope(
        "read_publications", "recommended",
        "sales-channel publish state",
        ("3a",),
    ),
    Scope(
        "read_checkouts", "recommended",
        "abandoned checkout read (wave 4 audit noted "
        "as 🟡 partial — this scope closes it)",
        ("4",),
    ),
    Scope(
        "read_analytics", "recommended",
        "dashboard + forecasting raw pulls",
        ("dashboard",),
    ),
    Scope(
        "read_reports", "recommended",
        "Reports API — Shopify's overnight rollups "
        "(wave 5f)",
        ("5f",),
    ),
    Scope(
        "read_shopify_payments_payouts", "recommended",
        "payouts + balance transactions (wave 5f). "
        "Shopify Payments only.",
        ("5f",),
    ),
    Scope(
        "read_shopify_payments_disputes", "recommended",
        "chargebacks + inquiries (wave 5b). "
        "Shopify Payments only.",
        ("5b",),
    ),
    Scope(
        "read_users", "plus_only",
        "staff account introspection (wave 5f). "
        "Shopify Plus only.",
        ("5f",),
    ),
)


# ── Writes ─────────────────────────────────────────────────


_WRITES: tuple[Scope, ...] = (
    Scope(
        "write_products", "required",
        "product CRUD, variants, images, metafield "
        "definitions, collections",
        ("1", "3a", "4b"),
    ),
    Scope(
        "write_orders", "required",
        "cancel / close / open / update / tags / risks "
        "(wave 3a + 5b). CRITICAL — owner-dialog flows "
        "fail without this",
        ("3a", "5b"),
    ),
    Scope(
        "write_customers", "required",
        "full customer CRUD + addresses + tags + "
        "metafields + segments + saved searches",
        ("2", "5d"),
    ),
    Scope(
        "write_inventory", "required",
        "stock updates from supplier sync",
        ("1",),
    ),
    Scope(
        "write_draft_orders", "required",
        "draft order create + invoice + complete "
        "(wave 1)",
        ("1",),
    ),
    Scope(
        "write_fulfillments", "required",
        "fulfillment create + tracking + cancel + "
        "fulfillment services (wave 2 + 5c)",
        ("2", "5c"),
    ),
    Scope(
        "write_content", "required",
        "blog posts, pages (About/FAQ), article comment "
        "moderation",
        ("4e", "5e"),
    ),
    Scope(
        "write_online_store_pages", "required",
        "narrower pages-only write complementing "
        "write_content; 2024+ Shopify wants both for page "
        "CRUD",
        ("4e",),
    ),
    Scope(
        "write_files", "required",
        "stagedUploadsCreate target write + image upload "
        "for products / articles / theme assets (wave 3a, "
        "3b, 4e)",
        ("3a", "3b", "4e"),
    ),
    Scope(
        "write_themes", "required",
        "theme customisation + settings_data + "
        "asset upsert",
        ("3b",),
    ),
    Scope(
        "write_script_tags", "required",
        "tracking pixels install (Meta/TikTok/GA)",
        ("store_configurator",),
    ),
    Scope(
        "write_price_rules", "required",
        "auto-create discount codes",
        ("1",),
    ),
    Scope(
        "write_discounts", "required",
        "new-format discount codes + automatic "
        "discounts (wave 5e)",
        ("1", "5e"),
    ),
    Scope(
        "write_shop_policies", "required",
        "auto-publish privacy / refund / ToS / shipping",
        ("store_configurator",),
    ),
    Scope(
        "write_online_store_navigation", "required",
        "main + footer menu updates",
        ("store_configurator",),
    ),
    Scope(
        "write_gift_cards", "required",
        "issue / disable gift cards (wave 4a). "
        "Requires Shopify approval — see README for the "
        "merchant request form.",
        ("4a",),
    ),
    Scope(
        "write_shipping", "required",
        "shipping zone rate CRUD + carrier services "
        "(wave 3b)",
        ("3b",),
    ),
    Scope(
        "write_marketing_events", "recommended",
        "attribution events for ad campaigns (wave 4d)",
        ("4d",),
    ),
    Scope(
        "write_markets", "recommended",
        "international market CRUD (wave 4c). Required "
        "for multi-region expansion",
        ("4c",),
    ),
    Scope(
        "write_locales", "recommended",
        "enable/disable/publish shop locales (wave 5a). "
        "Shopify 2024+ merges into write_translations.",
        ("5a",),
    ),
    Scope(
        "write_translations", "recommended",
        "2024+ replacement name for write_locales; "
        "shopLocaleEnable/Disable/Update mutations land "
        "on this scope on current API versions (wave 5a)",
        ("5a",),
    ),
    Scope(
        "write_metaobjects", "recommended",
        "brand-kit / testimonial / custom-object writes — "
        "content generators use this to seed structured "
        "sections referenced from theme assets (wave 4e)",
        ("4e", "5d"),
    ),
    Scope(
        "write_pixels", "recommended",
        "install Shopify web pixels (2024+ tracking "
        "replacement for raw script_tags where feasible). "
        "Used by store_configurator if SHOPAI_META_PIXEL_ID "
        "is set.",
        ("store_configurator",),
    ),
)


_ALL: tuple[Scope, ...] = _READS + _WRITES


# ── Public API ────────────────────────────────────────────


def all_scopes() -> tuple[Scope, ...]:
    return _ALL


def required_scopes() -> tuple[Scope, ...]:
    return tuple(s for s in _ALL if s.tier == "required")


def recommended_scopes() -> tuple[Scope, ...]:
    return tuple(s for s in _ALL if s.tier == "recommended")


def plus_scopes() -> tuple[Scope, ...]:
    return tuple(s for s in _ALL if s.tier == "plus_only")


def scope_string(
    *,
    include_recommended: bool = True,
    include_plus: bool = False,
) -> str:
    """Comma-separated scope list for the OAuth redirect.

    Default: required + recommended. Plus-only scopes are
    left off because they fail the install on non-Plus
    stores; callers explicitly opt in.
    """
    picks: list[Scope] = list(required_scopes())
    if include_recommended:
        picks.extend(recommended_scopes())
    if include_plus:
        picks.extend(plus_scopes())
    return ",".join(s.handle for s in picks)


def diff_granted(
    granted: Iterable[str],
) -> dict[str, list[Scope]]:
    """Diff a granted-handles iterable against the canonical
    list. Returns three buckets: granted / missing /
    extra."""
    granted_set = {
        str(s).strip() for s in granted if s
    }
    granted_out: list[Scope] = []
    missing_out: list[Scope] = []
    for scope in _ALL:
        if scope.handle in granted_set:
            granted_out.append(scope)
        else:
            missing_out.append(scope)
    canonical = {s.handle for s in _ALL}
    extra = sorted(granted_set - canonical)
    return {
        "granted": granted_out,
        "missing": missing_out,
        "extra": [
            Scope(
                handle=h, tier="unknown",
                why="granted but not requested by ShopAI",
                waves=(),
            )
            for h in extra
        ],
    }
