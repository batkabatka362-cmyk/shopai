"""Niche auto-detector from product data.

Wave 83: stores arrive untagged. Wave 73-82's niche-aware
substrate (orchestrator, cluster list, transfer scanner)
silently no-ops when niche is empty or "general", so a new
store benefits from NONE of the niche bias until the operator
manually tags it via Wave 77's ``shopai niche --set``.

This module ships a deterministic-first keyword classifier:

  detect_niche_from_products(products)
    -> NicheDetection(suggested, confidence, scores)

  suggest_niche_for_store(store_id)
    -> NicheDetection | None

## Algorithm

For each product, tokenize {title, tags, product_type, vendor}
into lowercased word/phrase tokens. Score each niche by counting
keyword matches across all products. Normalize by total
keyword hits to derive confidence.

Confidence bands:
  - "high":     >=70% of matches went to the top niche
  - "medium":   40-70%
  - "low":      <40% (heterogeneous catalog)
  - "no_data":  no products OR no keyword matches at all

When confidence is no_data, suggested = "general" (operator
should not auto-apply). Caller decides.

## Why deterministic + not LLM

  - New stores have 0-20 products at most. Keyword match is
    plenty.
  - Same consultant pattern as Wave 17/24/34/35: deterministic
    baseline ALWAYS runs; an AI nudge can be layered on top
    later without re-doing the substrate.
  - Reproducible: same products -> same suggestion. Operator
    can re-run after seeding products to refine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Per-niche keyword vocabulary. Tokens are lowercased exact
# words OR multi-word phrases. Multi-word phrases match the
# concatenated text (after lowercasing); single words match a
# whitespace-bounded token.
_NICHE_KEYWORDS: dict[str, list[str]] = {
    "beauty": [
        "beauty", "skincare", "skin care", "cosmetic",
        "cosmetics", "makeup", "make up", "lipstick",
        "foundation", "mascara", "eyeliner", "blush",
        "serum", "moisturizer", "moisturiser", "cleanser",
        "toner", "spf", "sunscreen", "fragrance", "perfume",
        "haircare", "hair care", "shampoo", "conditioner",
        "nail", "nails", "manicure", "pedicure", "spa",
        "anti-aging", "anti aging", "facial", "lotion",
        "balm", "scrub", "exfoliator",
    ],
    "fashion": [
        "fashion", "apparel", "clothing", "clothes", "shirt",
        "t-shirt", "tshirt", "tee", "dress", "dresses",
        "jeans", "pants", "trousers", "shorts", "skirt",
        "jacket", "coat", "hoodie", "sweater", "sweatshirt",
        "blouse", "suit", "blazer", "shoes", "sneakers",
        "boots", "heels", "sandals", "handbag", "bag",
        "purse", "wallet", "belt", "scarf", "hat", "cap",
        "sunglasses", "watch", "watches", "jewelry",
        "jewellery", "necklace", "bracelet", "earring",
        "earrings", "ring", "rings", "accessory",
        "accessories", "outfit", "lookbook",
    ],
    "home": [
        "home", "house", "furniture", "couch", "sofa", "chair",
        "table", "desk", "bed", "mattress", "pillow",
        "blanket", "duvet", "comforter", "sheet", "sheets",
        "rug", "rugs", "carpet", "lamp", "lamps", "lighting",
        "decor", "decoration", "wall art", "kitchenware",
        "cookware", "dinnerware", "cutlery", "utensil",
        "utensils", "appliance", "appliances", "vacuum",
        "candle", "candles", "vase", "planter", "garden",
        "outdoor", "patio", "curtain", "curtains",
    ],
    "tech": [
        "tech", "technology", "electronic", "electronics",
        "gadget", "gadgets", "phone", "smartphone",
        "headphone", "headphones", "earbud", "earbuds",
        "earphone", "earphones", "speaker", "speakers",
        "laptop", "computer", "tablet", "ipad", "monitor",
        "keyboard", "mouse", "charger", "cable", "adapter",
        "usb", "battery", "powerbank", "drone", "camera",
        "lens", "smart watch", "smartwatch", "wearable",
        "fitness tracker", "router", "wifi", "bluetooth",
        "gaming", "console", "vr", "headset",
    ],
    "food": [
        "food", "snack", "snacks", "beverage", "beverages",
        "drink", "drinks", "coffee", "tea", "espresso",
        "smoothie", "juice", "supplement", "supplements",
        "vitamin", "vitamins", "protein", "powder", "bar",
        "bars", "granola", "cereal", "chocolate", "candy",
        "cookie", "cookies", "spice", "spices", "sauce",
        "sauces", "seasoning", "honey", "syrup", "oil",
        "olive oil", "coconut oil", "organic", "vegan",
        "gluten free", "gluten-free", "keto", "paleo",
        "meal kit", "subscription box",
    ],
}


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]*")


@dataclass
class NicheDetection:
    suggested: str
    confidence: str
    scores: dict[str, int] = field(default_factory=dict)
    total_matches: int = 0
    products_analyzed: int = 0
    top_score_ratio: float = 0.0

    @property
    def is_actionable(self) -> bool:
        """``confidence`` is medium or high -- safe to apply."""
        return self.confidence in ("medium", "high")


def _extract_text_blob(product: dict[str, Any]) -> str:
    """Concatenate product fields into a single searchable
    blob. Lowercased, whitespace-normalized."""
    parts: list[str] = []
    for key in ("title", "product_type", "vendor"):
        val = product.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    tags = product.get("tags")
    if isinstance(tags, list):
        parts.extend(t for t in tags if isinstance(t, str))
    elif isinstance(tags, str) and tags:
        parts.append(tags)
    blob = " ".join(parts).lower()
    # Normalize repeated whitespace.
    return re.sub(r"\s+", " ", blob)


def _count_keyword_hits(blob: str, keywords: list[str]) -> int:
    """How many keywords from the niche vocab appear in this
    product's blob? Multi-word phrases match anywhere; single-
    word phrases use word-boundary regex so 'tech' doesn't
    match inside 'protechnical'."""
    hits = 0
    for kw in keywords:
        if " " in kw or "-" in kw:
            # Phrase / hyphenated -- direct substring match.
            if kw in blob:
                hits += 1
        else:
            # Single word -- word-boundary match.
            if re.search(rf"\b{re.escape(kw)}\b", blob):
                hits += 1
    return hits


def detect_niche_from_products(
    products: list[dict[str, Any]] | None,
) -> NicheDetection:
    """Run the deterministic classifier against a product list."""
    if not products:
        return NicheDetection(
            suggested="general",
            confidence="no_data",
            scores={},
            total_matches=0,
            products_analyzed=0,
            top_score_ratio=0.0,
        )
    scores: dict[str, int] = {n: 0 for n in _NICHE_KEYWORDS}
    products_analyzed = 0
    for p in products:
        if not isinstance(p, dict):
            continue
        products_analyzed += 1
        blob = _extract_text_blob(p)
        if not blob:
            continue
        for niche, kw_list in _NICHE_KEYWORDS.items():
            scores[niche] += _count_keyword_hits(blob, kw_list)
    total_matches = sum(scores.values())
    if total_matches == 0:
        return NicheDetection(
            suggested="general",
            confidence="no_data",
            scores=scores,
            total_matches=0,
            products_analyzed=products_analyzed,
            top_score_ratio=0.0,
        )
    # Pick the winner -- tie breaker is alphabetical for
    # determinism (no chance "tech" beats "food" due to dict
    # iteration order). sorted(... (-score, name)) puts the
    # highest score first, with ties broken by lexicographic
    # name ascending.
    top_niche = sorted(
        scores.items(), key=lambda kv: (-kv[1], kv[0]),
    )[0][0]
    top_score = scores[top_niche]
    ratio = top_score / total_matches if total_matches else 0.0
    if ratio >= 0.7:
        confidence = "high"
    elif ratio >= 0.4:
        confidence = "medium"
    else:
        confidence = "low"
    return NicheDetection(
        suggested=top_niche,
        confidence=confidence,
        scores=scores,
        total_matches=total_matches,
        products_analyzed=products_analyzed,
        top_score_ratio=round(ratio, 3),
    )


def suggest_niche_for_store(
    store_id: str,
    *,
    store_manager: Any = None,
    limit: int = 50,
) -> NicheDetection | None:
    """Pull recent products for one store + classify.

    Returns None when the store doesn't exist or the manager
    raises. Empty product list still returns a NicheDetection
    with confidence='no_data' so the caller can render a
    helpful message.
    """
    try:
        if store_manager is None:
            from data_pipeline.store.store_manager import StoreManager
            store_manager = StoreManager()
        if not store_manager.get_store(store_id):
            return None
        products = store_manager.get_products(
            store_id, limit=limit,
        ) or []
    except Exception:  # noqa: BLE001
        return None
    return detect_niche_from_products(products)
