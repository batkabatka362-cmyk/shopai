"""Auto-seed niche-aware starter products at store launch.

The launch_audit's ``active_products`` check fails on any
store with zero ACTIVE products -- a fresh storefront with
discounts, collections, and pages but nothing to BUY is the
single biggest "not launchable" failure mode. Operators
typically have to drop into Shopify admin and create a
handful of starter products by hand before the store can
take orders.

This module closes that gap with the same generator+applier
pattern as ``collection_seeder`` (PR #370). Given a niche,
``generate_starter_products`` returns 4-5 friendly product
specs ready to feed through the EXISTING
``SHOPIFY_CREATE_PRODUCT`` adapter. ``apply_starter_products``
pushes them and records via Pattern Z.

Each spec mirrors the adapter's friendly call shape::

    {
        "title": "Hydrating Vitamin C Serum",
        "description_html": "<p>Brightening formula ...</p>",
        "product_type": "Skincare",
        "vendor": "Acme Beauty",
        "tags": ["serum", "hydration", "starter"],
        "handle": "hydrating-vitamin-c-serum",
        "status": "ACTIVE",
        "seo_title": "...",
        "seo_description": "...",
    }

Niche-aware starter sets (4 products per niche):
  * beauty   -> Vitamin C Serum / Lip Tint / Dry Shampoo / Gift Box
  * fashion  -> Crewneck Tee / Denim Jeans / Tote Bag / Wool Scarf
  * tech     -> Wireless Earbuds / USB-C Hub / Smart Plug / Power Bank
  * home     -> Linen Throw / Pendant Lamp / Mug Set / Bed Sheet Set
  * food     -> Olive Oil / Hot Sauce / Coffee Beans / Sampler Box
  * general  -> Starter Item One / Two / Three / Four

The seed set is intentionally SMALL (4 items) and STARTERS,
not a real catalog. The operator is expected to replace
these with real products before going live -- the seeded
items are the bridge that lets ``shopai launch`` produce a
store passing the audit's active_products check even on a
brand-new store with no inventory. Tagged with ``starter``
so operators can bulk-archive them once their real catalog
lands.

Pattern Z: every seed run records via ``record_writeback``
so the autonomous loop can correlate seeded products with
later traffic / conversion outcomes.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Starter product specs per niche. Each entry is
# ``(title, description_html, product_type, tags)``. Handles
# + status are derived in :func:`generate_starter_products`.
_STARTER_SETS: dict[str, list[tuple[str, str, str, list[str]]]] = {
    "beauty": [
        ("Hydrating Vitamin C Serum",
         "<p>Brightening daily serum with stabilised "
         "vitamin C and hyaluronic acid. Lightweight, "
         "fragrance-free, suitable for all skin types.</p>",
         "Skincare",
         ["serum", "hydration", "vitamin-c", "starter"]),
        ("Tinted Lip Balm",
         "<p>Sheer wash of colour with overnight-balm "
         "comfort. Buildable, kiss-proof, naturally derived.</p>",
         "Makeup",
         ["lip", "balm", "tinted", "starter"]),
        ("Volumising Dry Shampoo",
         "<p>Refresh second-day hair instantly. Adds lift "
         "at the root without residue.</p>",
         "Hair Care",
         ["dry-shampoo", "volume", "starter"]),
        ("Essentials Gift Box",
         "<p>Best-seller sampler in giftable packaging. "
         "Three full-size + two travel-size favourites.</p>",
         "Gift Sets",
         ["gift", "bundle", "sampler", "starter"]),
    ],
    "fashion": [
        ("Heavyweight Crewneck Tee",
         "<p>Premium cotton crew in a relaxed cut. "
         "Pre-shrunk, garment-dyed, made to last.</p>",
         "Tops",
         ["tee", "crewneck", "cotton", "starter"]),
        ("Straight-Leg Denim Jeans",
         "<p>Mid-rise, straight through hip and thigh. "
         "Rigid 12oz selvedge denim.</p>",
         "Bottoms",
         ["jeans", "denim", "straight", "starter"]),
        ("Everyday Canvas Tote",
         "<p>Heavy 16oz canvas, reinforced strap, holds "
         "everything you carry.</p>",
         "Accessories",
         ["tote", "canvas", "bag", "starter"]),
        ("Merino Wool Scarf",
         "<p>Fine-gauge knit, soft enough for next-to-skin. "
         "Generous length, classic colour.</p>",
         "Accessories",
         ["scarf", "wool", "merino", "starter"]),
    ],
    "tech": [
        ("Wireless Earbuds Pro",
         "<p>Active noise cancellation, 30-hour battery, "
         "transparent mode. USB-C charging case.</p>",
         "Audio",
         ["earbuds", "wireless", "noise-cancelling", "starter"]),
        ("USB-C 7-in-1 Hub",
         "<p>HDMI 4K, two USB-A, two USB-C (one PD), SD + "
         "microSD. Aluminium body, pass-through power.</p>",
         "Accessories",
         ["hub", "usb-c", "dock", "starter"]),
        ("Smart Plug (Wi-Fi)",
         "<p>2.4 GHz Wi-Fi, voice assistant compatible, "
         "energy monitoring. No hub required.</p>",
         "Smart Home",
         ["smart-plug", "wifi", "automation", "starter"]),
        ("20,000 mAh Power Bank",
         "<p>Two outputs, USB-C PD 20W in/out, LCD charge "
         "display. Airline-safe capacity.</p>",
         "Gadgets",
         ["power-bank", "portable", "usb-c", "starter"]),
    ],
    "home": [
        ("Stonewashed Linen Throw",
         "<p>European flax, sandwashed for softness. "
         "Generous 140x180 cm.</p>",
         "Home Decor",
         ["throw", "linen", "blanket", "starter"]),
        ("Brass Pendant Lamp",
         "<p>Brushed brass shade with linen cord. E27 "
         "fitting; bulb sold separately.</p>",
         "Lighting",
         ["pendant", "lamp", "brass", "starter"]),
        ("Stoneware Mug Set (4)",
         "<p>Hand-thrown reactive glaze; no two identical. "
         "Dishwasher + microwave safe.</p>",
         "Kitchen",
         ["mug", "stoneware", "ceramic", "starter"]),
        ("Percale Bed Sheet Set",
         "<p>Long-staple cotton, 400-thread-count percale. "
         "Crisp, cool, oeko-tex certified.</p>",
         "Bedroom",
         ["sheets", "percale", "cotton", "starter"]),
    ],
    "food": [
        ("Single-Estate Olive Oil",
         "<p>Cold-extracted Spanish olive oil, harvest "
         "date on every bottle. 500 ml dark glass.</p>",
         "Pantry",
         ["olive-oil", "single-estate", "starter"]),
        ("Small-Batch Hot Sauce",
         "<p>Fermented chilli + smoked garlic. Bold, "
         "complex, addictive on everything.</p>",
         "Pantry",
         ["hot-sauce", "fermented", "starter"]),
        ("Single-Origin Coffee Beans (250g)",
         "<p>Washed Ethiopian, citrus-forward. Roasted "
         "weekly, ground or whole.</p>",
         "Drinks",
         ["coffee", "single-origin", "starter"]),
        ("Pantry Starter Sampler",
         "<p>Bestseller bundle: oil, vinegar, two sauces, "
         "and a salt blend. Giftable wood crate.</p>",
         "Gifts",
         ["sampler", "bundle", "gift", "starter"]),
    ],
    "general": [
        ("Starter Item One",
         "<p>Placeholder product -- replace with your "
         "first real listing.</p>",
         "General",
         ["starter", "placeholder"]),
        ("Starter Item Two",
         "<p>Placeholder product -- replace with your "
         "second real listing.</p>",
         "General",
         ["starter", "placeholder"]),
        ("Starter Item Three",
         "<p>Placeholder product -- replace with your "
         "third real listing.</p>",
         "General",
         ["starter", "placeholder"]),
        ("Starter Item Four",
         "<p>Placeholder product -- replace with your "
         "fourth real listing.</p>",
         "General",
         ["starter", "placeholder"]),
    ],
}

# ACTIVE so the audit's active_products check counts them.
# Switching to DRAFT defeats the entire purpose of the seeder.
_DEFAULT_STATUS: str = "ACTIVE"


def _slug(title: str) -> str:
    """Title -> URL handle. Lowercase + hyphen-separated."""
    s = (title or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "product"


def generate_starter_products(
    *,
    niche: str = "general",
    vendor: str = "",
) -> list[dict[str, Any]]:
    """Return the starter product specs for a niche.

    Args:
        niche: Lowercase niche key. Unknown niches fall back
            to ``general``.
        vendor: Optional vendor / brand label. When empty,
            the ``vendor`` field is omitted (Shopify defaults
            to the shop name).

    Returns:
        List of dicts ready to feed into
        ``SHOPIFY_CREATE_PRODUCT``. Empty list only if the
        niche set was somehow emptied (defensive; current
        sets are all non-empty).
    """
    niche_n = (niche or "general").strip().lower() or "general"
    entries = _STARTER_SETS.get(niche_n) or _STARTER_SETS["general"]
    vendor_clean = (vendor or "").strip()
    specs: list[dict[str, Any]] = []
    for title, description, product_type, tags in entries:
        spec: dict[str, Any] = {
            "title": title,
            "handle": _slug(title),
            "description_html": description,
            "product_type": product_type,
            "tags": list(tags),
            "status": _DEFAULT_STATUS,
        }
        if vendor_clean:
            spec["vendor"] = vendor_clean
        specs.append(spec)
    return specs


def apply_starter_products(
    specs: list[dict[str, Any]],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push each starter product spec via the
    SHOPIFY_CREATE_PRODUCT adapter.

    Args:
        specs: List of dicts from
            :func:`generate_starter_products`. Empty / non-
            list short-circuits.
        store_id: Optional per-store recording scope.

    Returns:
        ``{
            "applied_count": int,
            "results": list[dict],
        }`` -- one dict per product: ``{title, handle,
        ok, error}``.
    """
    if not isinstance(specs, list) or not specs:
        return {"applied_count": 0, "results": []}

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        results = [
            {
                "title": s.get("title", ""),
                "handle": s.get("handle", ""),
                "ok": False,
                "error": "router_unavailable",
            }
            for s in specs
        ]
        for r in results:
            _record(
                title=r["title"], handle=r["handle"],
                success=False, store_id=store_id,
                error=r["error"],
            )
        return {"applied_count": 0, "results": results}

    results: list[dict[str, Any]] = []
    applied_count = 0
    for spec in specs:
        title = spec.get("title", "")
        handle = spec.get("handle") or _slug(title)
        try:
            adapter_result = router.execute(capability, spec)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_seeder: router.execute raised "
                "for %s: %s", title, exc,
            )
            results.append({
                "title": title, "handle": handle,
                "ok": False,
                "error": f"adapter_raise: {exc}",
            })
            _record(
                title=title, handle=handle, success=False,
                store_id=store_id, error=str(exc),
            )
            continue
        ok = bool(getattr(adapter_result, "ok", False))
        error = getattr(adapter_result, "error", None)
        if ok:
            applied_count += 1
            results.append({
                "title": title, "handle": handle,
                "ok": True, "error": None,
            })
            _record(
                title=title, handle=handle, success=True,
                store_id=store_id, error=None,
            )
        else:
            results.append({
                "title": title, "handle": handle,
                "ok": False, "error": str(error or "unknown"),
            })
            _record(
                title=title, handle=handle, success=False,
                store_id=store_id, error=str(error or "unknown"),
            )

    return {"applied_count": applied_count, "results": results}


# ── Helpers ─────────────────────────────────────────────────


def _record(
    *,
    title: str,
    handle: str,
    success: bool,
    store_id: str | None,
    error: str | None,
) -> None:
    """Pattern Z hook -- record each seeded product so the
    autonomous loop can correlate seed runs with later
    traffic/conversion outcomes."""
    try:
        params: dict[str, Any] = {
            "title": title, "handle": handle,
        }
        if store_id:
            params["store_id"] = str(store_id)
        record_writeback(
            engine="store_setup",
            action_type="seed_product",
            capability="SHOPIFY_CREATE_PRODUCT",
            params=params,
            success=success,
            error=error,
            metrics={"seeded": 1 if success else 0},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_seeder record_writeback raised: %s", exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_seeder router import raised: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_seeder capability import raised: %s", exc,
        )
        return None
