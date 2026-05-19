"""Auto-seed niche-aware starter collections at store launch.

A fresh Shopify store with products but no collections looks
like a warehouse, not a storefront. Customers landing on the
homepage need browseable categories that match how they think
about the niche. Manually drafting collection titles + smart
rules is the same friction the policy/page generators removed.

This module is the launch-time collection seeder. Given a
niche, it returns 4-5 starter collection specs ready to push
through the EXISTING ``SHOPIFY_CREATE_COLLECTION`` adapter
(no new capability needed -- adapter is already wired).

Each spec mirrors the friendly call shape::

    {
        "title": "New Arrivals",
        "handle": "new-arrivals",
        "description_html": "<p>...</p>",
        "sort_order": "BEST_SELLING",
    }

Niche-aware starter sets:
  * beauty   -> Skincare / Makeup / Hair Care / Gift Sets
  * fashion  -> New Arrivals / Tops / Bottoms / Accessories / Sale
  * tech     -> Gadgets / Accessories / Smart Home / Audio
  * home     -> Home Decor / Lighting / Kitchen / Bedroom
  * food     -> New / Pantry / Drinks / Gifts
  * general  -> New Arrivals / Best Sellers / Sale / Gift Ideas

Pattern Z: every seed run records via ``record_writeback`` so
the autonomous learning loop can correlate seeded collections
with later browse / click-through outcomes.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Starter collection specs per niche. Each entry is
# ``(title, description_html)``. Handles + sort_order are
# derived in :func:`generate_starter_collections`.
_STARTER_SETS: dict[str, list[tuple[str, str]]] = {
    "beauty": [
        ("Skincare",
         "<p>Cleansers, serums, moisturisers -- the daily routine.</p>"),
        ("Makeup",
         "<p>Lips, eyes, face -- everyday and statement looks.</p>"),
        ("Hair Care",
         "<p>Shampoo, conditioner, styling -- for every hair type.</p>"),
        ("Gift Sets",
         "<p>Curated bundles, ready to give.</p>"),
    ],
    "fashion": [
        ("New Arrivals",
         "<p>The latest drops, fresh off the rack.</p>"),
        ("Tops",
         "<p>Tees, blouses, sweaters -- staples + statement.</p>"),
        ("Bottoms",
         "<p>Jeans, pants, skirts -- every silhouette.</p>"),
        ("Accessories",
         "<p>Bags, jewellery, belts -- the finishing touch.</p>"),
        ("Sale",
         "<p>Discounted styles -- limited stock.</p>"),
    ],
    "tech": [
        ("Gadgets",
         "<p>Smart devices for everyday life.</p>"),
        ("Accessories",
         "<p>Cables, cases, stands -- the essentials.</p>"),
        ("Smart Home",
         "<p>Lights, plugs, sensors -- automate your space.</p>"),
        ("Audio",
         "<p>Headphones, speakers, mics -- premium sound.</p>"),
    ],
    "home": [
        ("Home Decor",
         "<p>Art, accents, statement pieces.</p>"),
        ("Lighting",
         "<p>Floor lamps, pendants, smart bulbs.</p>"),
        ("Kitchen",
         "<p>Tools, gadgets, and dinnerware.</p>"),
        ("Bedroom",
         "<p>Sheets, throws, and bedside essentials.</p>"),
    ],
    "food": [
        ("New",
         "<p>Just landed -- latest additions to the pantry.</p>"),
        ("Pantry",
         "<p>Staples: oils, sauces, dry goods.</p>"),
        ("Drinks",
         "<p>Coffee, tea, sodas -- and everything between.</p>"),
        ("Gifts",
         "<p>Bundles + sampler sets, gift-wrapped.</p>"),
    ],
    "general": [
        ("New Arrivals",
         "<p>The latest drops.</p>"),
        ("Best Sellers",
         "<p>What everyone's buying right now.</p>"),
        ("Sale",
         "<p>Limited-time discounts.</p>"),
        ("Gift Ideas",
         "<p>Curated picks for every occasion.</p>"),
    ],
}

# When to apply best-selling sort vs alphabetical / manual.
# Manual collections (no rule set) default to best-selling
# since that's what most operators want.
_DEFAULT_SORT_ORDER: str = "BEST_SELLING"


def _slug(title: str) -> str:
    """Title -> URL handle. Lowercase + hyphen-separated."""
    s = (title or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "collection"


def generate_starter_collections(
    *,
    niche: str = "general",
) -> list[dict[str, Any]]:
    """Return the starter collection specs for a niche.

    Args:
        niche: Lowercase niche key. Unknown niches fall back
            to ``general``.

    Returns:
        List of dicts ready to feed into
        ``SHOPIFY_CREATE_COLLECTION``. Empty list only if the
        niche set was somehow emptied (defensive; current
        sets are all non-empty).
    """
    niche_n = (niche or "general").strip().lower() or "general"
    entries = _STARTER_SETS.get(niche_n) or _STARTER_SETS["general"]
    specs: list[dict[str, Any]] = []
    for title, description in entries:
        specs.append({
            "title": title,
            "handle": _slug(title),
            "description_html": description,
            "sort_order": _DEFAULT_SORT_ORDER,
        })
    return specs


def apply_starter_collections(
    specs: list[dict[str, Any]],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push each starter collection spec via the
    SHOPIFY_CREATE_COLLECTION adapter.

    Args:
        specs: List of dicts from
            :func:`generate_starter_collections`. Empty / non-
            list short-circuits.
        store_id: Optional per-store recording scope.

    Returns:
        ``{
            "applied_count": int,
            "results": list[dict],
        }`` -- one dict per collection: ``{title, handle,
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
                "collection_seeder: router.execute raised "
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
                "ok": False,
                "error": str(error or "rejected"),
            })
            _record(
                title=title, handle=handle, success=False,
                store_id=store_id,
                error=str(error or "rejected"),
            )
    return {
        "applied_count": applied_count,
        "results": results,
    }


# --- helpers --------------------------------------------------


def _record(
    *,
    title: str,
    handle: str,
    success: bool,
    store_id: str | None,
    error: str | None,
) -> None:
    params: dict[str, Any] = {
        "title": title,
        "handle": handle,
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_starter_collection",
            capability="SHOPIFY_CREATE_COLLECTION",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "collection_title": title,
                "handle": handle,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "collection_seeder record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "collection_seeder router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_COLLECTION
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "collection_seeder capability resolve failed: %s",
            exc,
        )
        return None
