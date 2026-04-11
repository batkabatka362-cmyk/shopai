"""Social proof audit — photo reviews convert 4.5x better than no reviews."""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_float, safe_int

SOCIAL_PROOF_MULTIPLIERS = {
    "video_review": 6.0,
    "photo_review": 4.5,
    "text_review": 2.5,
    "star_rating_only": 1.5,
    "no_reviews": 1.0,
}


def _social_proof_action(level: str, count: int) -> str:
    if level == "no_reviews":
        return "Send post-purchase review request email with photo incentive"
    if level == "star_rating_only":
        return "Offer $5 coupon for photo/video reviews"
    if level == "text_review" and count < 10:
        return "Need more reviews — add review request to unboxing insert card"
    return "Strong — consider featuring in ads"


def audit_social_proof(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit social proof across products — photo reviews convert 4.5x better than no reviews."""
    results = []
    for product in products:
        if not isinstance(product, dict):
            continue

        name = product.get("title", product.get("name", "Unknown"))
        review_count = safe_int(product.get("review_count", product.get("reviews", 0)))
        rating = safe_float(product.get("rating", 0))
        has_photos = product.get("has_photo_reviews", False)
        has_video = product.get("has_video_reviews", False)

        # Determine social proof level
        if has_video and review_count >= 10:
            level = "video_review"
        elif has_photos and review_count >= 5:
            level = "photo_review"
        elif review_count >= 3:
            level = "text_review"
        elif rating > 0:
            level = "star_rating_only"
        else:
            level = "no_reviews"

        multiplier = SOCIAL_PROOF_MULTIPLIERS[level]
        results.append({
            "product": name,
            "review_count": review_count,
            "rating": rating,
            "social_proof_level": level,
            "conversion_multiplier": f"{multiplier}x",
            "improvement_action": _social_proof_action(level, review_count),
        })

    # Sort by weakest social proof first (most opportunity)
    results.sort(key=lambda r: SOCIAL_PROOF_MULTIPLIERS.get(r["social_proof_level"], 0))

    weak = [r for r in results if r["social_proof_level"] in ("no_reviews", "star_rating_only")]
    return {
        "products_audited": len(results),
        "weak_social_proof": len(weak),
        "details": results,
        "recommendation": (
            f"{len(weak)} products need better social proof. "
            "Priority: get photo reviews on top-selling products."
            if weak else "Social proof is strong across products."
        ),
    }
