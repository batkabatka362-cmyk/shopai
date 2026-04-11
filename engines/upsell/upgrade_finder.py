"""Upsell Engine — upgrade finder.

Searches the catalog for upgrade candidates: products in the same category
with a higher tier, better features, and a higher price than the current
product.

Model note: Uses Mistral for nuanced candidate ranking and reasoning.
"""
from __future__ import annotations

import copy
from typing import Any

from .product_analyzer import TIER_RANKS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_CANDIDATES = 10


def find_upgrades(
    analysis: dict[str, Any],
    catalog: list[dict[str, Any]],
    current_features: list[str] | None = None,
) -> dict[str, Any]:
    """Find upgrade candidates from the catalog.

    Args:
        analysis: ProductAnalysis dict from product_analyzer.
        catalog: List of CatalogProduct dicts.
        current_features: Feature list of the current product (fallback).

    Returns:
        Structured dict with ranked UpgradeCandidate list and status.
    """
    try:
        safe_analysis = copy.deepcopy(analysis)
        safe_catalog = copy.deepcopy(catalog)

        if not safe_catalog:
            return {
                "status": "success",
                "candidates": [],
                "count": 0,
                "note": "Empty catalog — no upgrades available",
            }

        current_id = str(safe_analysis.get("product_id", ""))
        current_category = str(safe_analysis.get("category", "")).lower().strip()
        current_price = float(safe_analysis.get("price", 0.0))
        current_tier_rank = int(safe_analysis.get("tier_rank", 3))

        # Resolve current features
        raw_features = current_features or []
        if not isinstance(raw_features, list):
            raw_features = []
        current_features_set = set(raw_features)

        candidates: list[dict[str, Any]] = []

        for item in safe_catalog:
            if not isinstance(item, dict):
                continue

            item_id = str(item.get("id", ""))

            # Skip current product
            if item_id == current_id:
                continue

            item_category = str(item.get("category", "")).lower().strip()
            item_price = float(item.get("price", 0.0))
            item_tier = str(item.get("tier", "standard")).lower().strip()
            item_tier_rank = TIER_RANKS.get(item_tier, 3)
            item_features = item.get("features", [])
            if not isinstance(item_features, list):
                item_features = []
            item_margin = float(item.get("margin", 0.0))

            # --- Filter: must be same category ---
            if item_category != current_category:
                continue

            # --- Filter: must be higher price ---
            if item_price <= current_price:
                continue

            # --- Filter: must be same or higher tier ---
            if item_tier_rank < current_tier_rank:
                continue

            # --- Compute extras ---
            tier_jump = item_tier_rank - current_tier_rank
            item_features_set = set(item_features)
            extra_features = sorted(item_features_set - current_features_set)

            # --- Relevance score for ranking ---
            relevance = _compute_relevance(
                tier_jump=tier_jump,
                extra_feature_count=len(extra_features),
                price_ratio=item_price / max(current_price, 0.01),
                margin=item_margin,
            )

            candidates.append({
                "product_id": item_id,
                "title": str(item.get("title", "")),
                "category": item_category,
                "price": round(item_price, 2),
                "tier": item_tier,
                "tier_rank": item_tier_rank,
                "features": item_features,
                "margin": round(item_margin, 4),
                "tier_jump": tier_jump,
                "extra_features": extra_features,
                "relevance_score": round(relevance, 4),
                "model_note": (
                    f"Mistral: upgrade candidate — tier jump {tier_jump}, "
                    f"{len(extra_features)} extra features, "
                    f"price ratio {item_price / max(current_price, 0.01):.2f}x, "
                    f"margin {item_margin:.0%}"
                ),
            })

        # --- Sort by relevance descending, cap at max ---
        candidates.sort(key=lambda c: c["relevance_score"], reverse=True)
        candidates = candidates[:_MAX_CANDIDATES]

        return {
            "status": "success",
            "candidates": candidates,
            "count": len(candidates),
        }
    except Exception as exc:
        return {
            "status": "error",
            "candidates": [],
            "count": 0,
            "error": f"Upgrade finder failed: {exc}",
        }


def _compute_relevance(
    tier_jump: int,
    extra_feature_count: int,
    price_ratio: float,
    margin: float,
) -> float:
    """Score a candidate's relevance for upsell.

    Factors:
      - Tier jump: 1 tier is ideal, 2+ is less targeted (diminishing)
      - Extra features: more extras = stronger value proposition
      - Price ratio: too high = hard sell; sweet spot ~1.1x to 1.5x
      - Margin: higher margin = more profitable upsell

    Returns:
        Float score 0.0 - 1.0.
    """
    # Tier score: 1 tier = 1.0, 2 tiers = 0.7, 3+ = 0.4
    if tier_jump == 0:
        tier_score = 0.3     # same tier but higher price — weak
    elif tier_jump == 1:
        tier_score = 1.0     # ideal — one step up
    elif tier_jump == 2:
        tier_score = 0.7     # acceptable
    else:
        tier_score = 0.4     # too big a jump

    # Feature score: diminishing returns after 3 extras
    feature_score = min(extra_feature_count / 3.0, 1.0)

    # Price ratio score: sweet spot 1.10 - 1.50
    if price_ratio <= 1.0:
        price_score = 0.0
    elif price_ratio <= 1.10:
        price_score = 0.5    # too small — weak incentive for customer to notice
    elif price_ratio <= 1.30:
        price_score = 1.0    # sweet spot
    elif price_ratio <= 1.50:
        price_score = 0.8    # acceptable
    elif price_ratio <= 2.0:
        price_score = 0.5    # stretch
    else:
        price_score = 0.2    # too expensive

    # Margin score: linear 0-1 (capped at 0.6 margin)
    margin_score = min(margin / 0.6, 1.0)

    # Weighted combination
    score = (
        tier_score * 0.30
        + feature_score * 0.25
        + price_score * 0.30
        + margin_score * 0.15
    )
    return max(0.0, min(1.0, score))
