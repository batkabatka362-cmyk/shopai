"""
knowledge.py — Brand building heuristics, diagnostics, and expert tips.

Encodes practitioner knowledge about brand coherence so the engine
can explain why a product is a poor fit and what to do about it.
"""

# ---------------------------------------------------------------------------
# Practitioner heuristics
# ---------------------------------------------------------------------------
BRAND_HEURISTICS = [
    {
        "id": "mixed_tiers_kills_trust",
        "topic": "price_coherence",
        "insight": "Selling luxury and budget in the same store kills customer trust.",
        "action": "Keep all products within 1 quality tier of each other.",
    },
    {
        "id": "coherence_over_variety",
        "topic": "catalog_strategy",
        "insight": "Brand coherence matters more than product variety for conversion.",
        "action": "Remove low-fit products even if they sell; they hurt the brand long-term.",
    },
    {
        "id": "max_three_categories",
        "topic": "category_focus",
        "insight": "New stores should stock a maximum of 3 categories to build authority.",
        "action": "Pick your top 3 categories and go deep before expanding.",
    },
    {
        "id": "price_anchor",
        "topic": "pricing",
        "insight": "Your highest-priced item sets customer expectations for the whole store.",
        "action": "Ensure your anchor product represents your brand tier accurately.",
    },
    {
        "id": "demographic_whiplash",
        "topic": "targeting",
        "insight": "Targeting gen_z and boomers simultaneously confuses your marketing.",
        "action": "Pick one primary demographic and one adjacent secondary.",
    },
    {
        "id": "values_alignment",
        "topic": "brand_values",
        "insight": "Products contradicting your stated brand values cause PR crises.",
        "action": "Audit every product for value conflicts before listing.",
    },
    {
        "id": "catalog_size_signal",
        "topic": "catalog_strategy",
        "insight": "Under 50 SKUs looks boutique/curated; over 500 looks like a marketplace.",
        "action": "Match your SKU count to your brand archetype expectations.",
    },
    {
        "id": "brand_story_test",
        "topic": "coherence",
        "insight": "If you cannot explain why a product is in your store in one sentence, cut it.",
        "action": "Apply the one-sentence test before adding any new product.",
    },
    {
        "id": "quality_floor",
        "topic": "quality",
        "insight": "One bad product tanks reviews for the whole store on marketplaces.",
        "action": "Set a minimum rating threshold and enforce it without exceptions.",
    },
    {
        "id": "seasonal_brand_drift",
        "topic": "catalog_strategy",
        "insight": "Seasonal products that do not match your core brand cause drift over time.",
        "action": "Only add seasonal items that reinforce your brand identity.",
    },
]


def diagnose_brand_issues(results, brand_archetype=None):
    """Analyze brand fit results and return actionable diagnostics.

    Parameters
    ----------
    results : list[dict]
        Each dict has 'score', 'flags', and product info.
    brand_archetype : str or None
        The store's declared brand archetype.

    Returns
    -------
    list[str]  Human-readable diagnostic messages.
    """
    diagnostics = []
    total = len(results)
    if total == 0:
        return ["No products to diagnose."]

    poor_fit = [r for r in results if r.get("score", 0) < 40]
    avg_score = sum(r.get("score", 0) for r in results) / total

    if len(poor_fit) > total * 0.3:
        diagnostics.append(
            f"{len(poor_fit)}/{total} products are a poor brand fit (score < 40). "
            "Your sourcing may not match your brand identity."
        )

    if avg_score < 50:
        diagnostics.append(
            f"Average brand fit score is {avg_score:.0f}/100. "
            "Consider narrowing your product selection criteria."
        )

    all_flags = []
    for r in results:
        all_flags.extend(r.get("flags", []))

    flag_counts = {}
    for f in all_flags:
        flag_counts[f] = flag_counts.get(f, 0) + 1

    for flag, count in sorted(flag_counts.items(), key=lambda x: -x[1]):
        if count >= 3:
            matching = [h for h in BRAND_HEURISTICS if h["topic"] == flag]
            for h in matching:
                diagnostics.append(f"[{flag}] {h['insight']}")
                break
            else:
                diagnostics.append(f"Recurring issue: '{flag}' flagged on {count} products.")

    if not diagnostics:
        diagnostics.append("Products are well-aligned with brand identity.")

    return diagnostics


def get_brand_tips(topic=None):
    """Return brand heuristics, optionally filtered by topic."""
    if topic:
        return [h for h in BRAND_HEURISTICS if h["topic"] == topic]
    return list(BRAND_HEURISTICS)
