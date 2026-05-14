"""Engine → primary-goal mapping.

Each ShopAI engine has a primary goal it optimizes for. When a
merchant-approved action lands successfully, that's positive
evidence for the engine's primary goal; a failed action is
negative evidence. The mapping lets ``goal_feedback`` translate
approval-queue outcomes into per-goal effectiveness updates.

A given engine has exactly ONE primary goal in this v1 mapping.
Multi-goal engines are deferred — most engines have a clean
primary, and adding weighted contributions for the few that
straddle ("dynamic_pricing" supports both maximize_profit AND
survive_crisis) introduces tuning surface we don't yet have
data to set.

Goals reference the names in :data:`core.goals.goal_manager.GOAL_DEFINITIONS`:

  * ``maximize_profit``     — margin / cost / pricing levers
  * ``grow_customers``      — retention / acquisition / churn
  * ``increase_aov``        — bundling / upsell / cross-sell
  * ``survive_crisis``      — emergency cost-cutting / risk
  * ``capture_opportunity`` — seasonal / trending / time-sensitive
"""
from __future__ import annotations


# Source-of-truth mapping. Engines absent from this dict
# contribute to the goal label ``"unmapped"`` (a neutral
# bucket; outcomes recorded under it don't affect any
# real goal's EMA).
ENGINE_GOAL_MAP: dict[str, str] = {
    # ─ Profit / margin levers ─────────────────────────────
    "discount_strategy": "maximize_profit",
    "dynamic_pricing": "maximize_profit",
    "pricing": "maximize_profit",
    "profit_optimization": "maximize_profit",
    "wholesale_b2b": "maximize_profit",
    "shipping_optimization": "maximize_profit",
    "tax": "maximize_profit",

    # ─ Customer growth / retention ────────────────────────
    "loyalty": "grow_customers",
    "cart_recovery": "grow_customers",
    "browse_recovery": "grow_customers",
    "churn_prediction": "grow_customers",
    "customer_segmentation": "grow_customers",
    "email_marketing": "grow_customers",
    "affiliate": "grow_customers",
    "nps_engine": "grow_customers",
    "review_management": "grow_customers",
    "customer_service": "grow_customers",
    "chatbot": "grow_customers",

    # ─ AOV / order-size levers ────────────────────────────
    "bundle": "increase_aov",
    "upsell": "increase_aov",
    "cross_sell": "increase_aov",

    # ─ Crisis / risk-protection ───────────────────────────
    "fraud_detection": "survive_crisis",
    "returns_management": "survive_crisis",
    "product_lifecycle": "survive_crisis",
    "inventory": "survive_crisis",

    # ─ Opportunity capture ────────────────────────────────
    "trend_detection": "capture_opportunity",
    "ads_spy": "capture_opportunity",
    "campaign_strategy": "capture_opportunity",
    "creative": "capture_opportunity",
    "roas_guardrails": "capture_opportunity",
    "landing_page": "capture_opportunity",
    "social_media": "capture_opportunity",
    "product_research": "capture_opportunity",

    # ─ Catalog hygiene (defaults to profit — it removes
    #   dead weight from the storefront, doesn't directly
    #   grow customers or AOV) ──────────────────────────────
    "tag_management": "maximize_profit",
    "search_optimization": "maximize_profit",
    "content_generation": "maximize_profit",
    "catalog": "maximize_profit",
    "image_optimization": "maximize_profit",
}


_UNMAPPED = "unmapped"


def goal_for_engine(engine: str) -> str:
    """Return the primary goal name for ``engine``.

    Returns ``"unmapped"`` for engines absent from the table —
    callers MAY treat this as "skip outcome recording" rather
    than fabricate a goal contribution.
    """
    if not isinstance(engine, str):
        return _UNMAPPED
    return ENGINE_GOAL_MAP.get(engine.strip(), _UNMAPPED)


def is_mapped(engine: str) -> bool:
    """``True`` when ``engine`` has a primary-goal binding."""
    return goal_for_engine(engine) != _UNMAPPED


def engines_for_goal(goal: str) -> list[str]:
    """All engines whose primary goal is ``goal``. Sorted for
    deterministic test output. Returns an empty list for an
    unknown goal name.
    """
    return sorted(
        engine for engine, g in ENGINE_GOAL_MAP.items() if g == goal
    )
