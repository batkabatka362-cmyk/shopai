"""Second batch: post-launch operational engines.

These are the engines that operate on an already-launched
store -- they DON'T close launch_audit checks (the store is
already launchable), but they're how the autonomous merchant
EARNS REVENUE day-to-day. Per the north-star bible, "launchable"
is mid-game; "earning revenue" is the long game and these
engines are the substrate for it.

Coverage of this batch:
  - Phase 6 writebacks: loyalty, discount_strategy,
    dynamic_pricing, tag_management, affiliate,
    product_lifecycle.
  - Recovery flows: cart_recovery, browse_recovery,
    churn_prediction.
  - Catalog operations: bundle, cohort_analysis,
    customer_journey, cross_sell.
  - Demand + inventory: catalog, demand_analysis.

Each engine declares:
  - ``module_path`` -- importable Python path to either the
    flow class or the writeback function.
  - ``composes_with`` -- typical chains. e.g. churn_prediction
    -> cart_recovery, loyalty -> tag_management.
  - ``tags`` -- coarse categorisation for planner filtering
    (post-launch, revenue, retention, acquisition, ...).

Side effects are described in plain English so an LLM
planner can reason about safety: "writes to discount codes,
records via Pattern Z".
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    register_capability,
)


def register_all() -> None:
    """Idempotent registration of every post-launch
    operational engine. Called from
    ``core.capability_registry.bootstrap.ensure_registered``.
    """

    # ── Phase 6 writeback engines ─────────────────────────

    register_capability(Capability(
        name="loyalty",
        kind=CapabilityKind.ENGINE,
        description=(
            "Loyalty program engine: scores customers by "
            "purchase + recency + engagement, assigns tiers, "
            "and (with apply_rewards=True) mints per-customer "
            "discount codes via discount_minter."
        ),
        when_to_use=(
            "Use when the goal involves repeat-purchase "
            "rewards, VIP customer treatment, tier-based "
            "perks, or retaining high-value customers."
        ),
        module_path="engines.loyalty.flow:LoyaltyEngine",
        inputs={
            "data": "{customers: list, orders: list, ...}",
            "data.apply_rewards": "bool (opt-in for writes)",
        },
        outputs={
            "status": "success|error",
            "data": "{tiers, rewards, minted_codes}",
            "minted_codes": "list when apply_rewards=True",
        },
        side_effects=[
            "with apply_rewards=True: creates discount "
            "codes via SHOPIFY_CREATE_DISCOUNT",
            "records SHOPAI_LOYALTY_MINT_REWARD via Pattern Z",
        ],
        scopes_used=["read_customers", "write_discounts"],
        composes_with=["tag_management", "cart_recovery"],
        tags=["post-launch", "retention", "revenue", "loyalty"],
    ))

    register_capability(Capability(
        name="discount_strategy",
        kind=CapabilityKind.ENGINE,
        description=(
            "Promotional discount strategy engine: scores "
            "discount opportunities by margin / "
            "cannibalisation / demand and (with "
            "apply_discount=True) mints storewide promo "
            "codes."
        ),
        when_to_use=(
            "Use when the goal involves promotions, "
            "campaigns, sales events, BFCM-style discounts, "
            "or storewide percentage-off codes. NOT for the "
            "welcome discount (that's welcome_discount in "
            "the launch chain)."
        ),
        module_path=(
            "engines.discount_strategy.flow:"
            "DiscountStrategyEngine"
        ),
        side_effects=[
            "with apply_discount=True: creates discount "
            "codes",
            "records via Pattern Z",
        ],
        scopes_used=["write_discounts"],
        composes_with=["demand_analysis", "audience_targeting"],
        tags=["post-launch", "marketing", "revenue",
              "discount"],
    ))

    register_capability(Capability(
        name="dynamic_pricing",
        kind=CapabilityKind.ENGINE,
        description=(
            "Per-product dynamic pricing engine: aggregates "
            "demand / inventory / competition / time-of-day "
            "signals, proposes price adjustments, and "
            "validates them through change_validator. With "
            "apply_pricing=True, writes via "
            "SHOPIFY_UPDATE_VARIANTS."
        ),
        when_to_use=(
            "Use when the goal involves pricing, margin "
            "optimisation, repricing, price testing, or "
            "competitive price matching."
        ),
        module_path=(
            "engines.dynamic_pricing.flow:DynamicPricingEngine"
        ),
        side_effects=[
            "with apply_pricing=True: updates Shopify "
            "variant prices via SHOPIFY_UPDATE_VARIANTS",
            "records via Pattern Z",
        ],
        scopes_used=["write_products"],
        composes_with=["competition_analyzer",
                       "demand_analysis"],
        tags=["post-launch", "pricing", "revenue"],
    ))

    register_capability(Capability(
        name="tag_management",
        kind=CapabilityKind.ENGINE,
        description=(
            "Auto-generates product tags from category + "
            "attributes + ML signal. With apply_tags=True, "
            "merges with existing tags (preserves them) and "
            "writes via SHOPIFY_UPDATE_PRODUCT."
        ),
        when_to_use=(
            "Use when the goal involves product tagging, "
            "filterable navigation, or improving search "
            "discoverability via tags."
        ),
        module_path=(
            "engines.tag_management.flow:TagManagementEngine"
        ),
        side_effects=[
            "with apply_tags=True: merges-then-writes "
            "Shopify product tags",
            "records via Pattern Z",
        ],
        scopes_used=["write_products"],
        composes_with=["cross_sell", "customer_journey"],
        tags=["post-launch", "products", "seo",
              "discoverability"],
    ))

    register_capability(Capability(
        name="affiliate",
        kind=CapabilityKind.ENGINE,
        description=(
            "Affiliate / partner program engine: tracks "
            "referrals, scores partners, calculates "
            "commissions, and (with apply_commissions=True) "
            "pays out via SHOPIFY_CREATE_GIFT_CARD."
        ),
        when_to_use=(
            "Use when the goal involves affiliate / "
            "influencer payouts, partner program management, "
            "or commission tracking. Gift cards instead of "
            "discount codes -- payment vs promotion."
        ),
        module_path="engines.affiliate.flow:AffiliateEngine",
        side_effects=[
            "with apply_commissions=True: creates gift "
            "cards via SHOPIFY_CREATE_GIFT_CARD",
            "records via Pattern Z",
        ],
        scopes_used=["write_gift_cards"],
        tags=["post-launch", "acquisition", "revenue",
              "affiliate"],
    ))

    register_capability(Capability(
        name="product_lifecycle",
        kind=CapabilityKind.ENGINE,
        description=(
            "Product lifecycle stage classifier: introduces "
            "/ growth / mature / decline. With "
            "apply_lifecycle=True, archives declining "
            "products via SHOPIFY_UPDATE_PRODUCT status."
        ),
        when_to_use=(
            "Use when the goal involves catalog hygiene, "
            "archiving dead SKUs, identifying winners, or "
            "deciding which products to promote vs retire."
        ),
        module_path=(
            "engines.product_lifecycle.flow:"
            "ProductLifecycleEngine"
        ),
        side_effects=[
            "with apply_lifecycle=True: changes product "
            "status (ACTIVE/ARCHIVED) via "
            "SHOPIFY_UPDATE_PRODUCT",
            "records via Pattern Z",
        ],
        scopes_used=["write_products"],
        composes_with=["demand_analysis",
                       "customer_journey"],
        tags=["post-launch", "catalog", "hygiene"],
    ))

    # ── Recovery + retention engines ──────────────────────

    register_capability(Capability(
        name="cart_recovery",
        kind=CapabilityKind.ENGINE,
        description=(
            "Abandoned-cart recovery engine: identifies "
            "abandoned checkouts, scores by recoverability, "
            "and mints per-customer recovery discount codes."
        ),
        when_to_use=(
            "Use when the goal involves recapturing lost "
            "carts, reducing abandonment, or recovering "
            "incomplete checkouts."
        ),
        module_path=(
            "engines.cart_recovery.flow:CartRecoveryEngine"
        ),
        side_effects=[
            "creates recovery discount codes",
            "records via Pattern Z",
        ],
        scopes_used=["write_discounts"],
        composes_with=["customer_journey", "email_marketing"],
        tags=["post-launch", "retention", "revenue",
              "abandoned-cart"],
    ))

    register_capability(Capability(
        name="browse_recovery",
        kind=CapabilityKind.ENGINE,
        description=(
            "Browse-abandonment recovery engine: identifies "
            "visitors who viewed but didn't buy, mints "
            "browse-recovery codes."
        ),
        when_to_use=(
            "Use when the goal involves converting "
            "browsers to buyers, retargeting site "
            "visitors, or recovering pre-cart interest."
        ),
        module_path=(
            "engines.browse_recovery.flow:"
            "BrowseRecoveryEngine"
        ),
        side_effects=[
            "creates browse-recovery discount codes",
            "records via Pattern Z",
        ],
        scopes_used=["write_discounts"],
        composes_with=["customer_journey"],
        tags=["post-launch", "acquisition", "retention",
              "browse-recovery"],
    ))

    register_capability(Capability(
        name="churn_prediction",
        kind=CapabilityKind.ENGINE,
        description=(
            "Churn-risk classifier: scores customers by "
            "likelihood to churn based on recency / "
            "frequency / engagement signal."
        ),
        when_to_use=(
            "Use when the goal involves retention, "
            "preventing customer churn, identifying at-risk "
            "VIPs, or feeding a retention campaign."
        ),
        module_path=(
            "engines.churn_prediction.flow:"
            "ChurnPredictionEngine"
        ),
        composes_with=["cart_recovery", "loyalty"],
        tags=["post-launch", "retention", "analysis"],
    ))

    # ── Catalog + audience engines ────────────────────────

    register_capability(Capability(
        name="bundle",
        kind=CapabilityKind.ENGINE,
        description=(
            "Product-bundle recommender: identifies products "
            "frequently bought together and proposes bundle "
            "SKUs / pricing."
        ),
        when_to_use=(
            "Use when the goal involves cross-sell bundles, "
            "increasing AOV via combos, or building "
            "frequently-bought-together suggestions."
        ),
        module_path="engines.bundle.flow:BundleEngine",
        composes_with=["cross_sell", "cohort_analysis"],
        tags=["post-launch", "revenue", "cross-sell"],
    ))

    register_capability(Capability(
        name="cross_sell",
        kind=CapabilityKind.ENGINE,
        description=(
            "Cross-sell / upsell recommender: per-product "
            "complementary item suggestions."
        ),
        when_to_use=(
            "Use when the goal involves increasing "
            "average order value via complementary "
            "products."
        ),
        module_path="engines.cross_sell.flow:CrossSellEngine",
        composes_with=["bundle", "tag_management"],
        tags=["post-launch", "revenue", "cross-sell"],
    ))

    register_capability(Capability(
        name="cohort_analysis",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer cohort analyser: groups customers by "
            "acquisition month + LTV trajectory."
        ),
        when_to_use=(
            "Use when the goal involves cohort retention "
            "analysis, LTV by acquisition channel, or "
            "identifying high-value cohorts."
        ),
        module_path=(
            "engines.cohort_analysis.flow:CohortAnalysisEngine"
        ),
        composes_with=["churn_prediction", "loyalty"],
        tags=["post-launch", "analytics"],
    ))

    register_capability(Capability(
        name="customer_journey",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer journey mapper: stages customers by "
            "lifecycle (visitor / first-time / repeat / VIP)."
        ),
        when_to_use=(
            "Use when the goal involves segmenting "
            "customers by lifecycle stage or triggering "
            "stage-appropriate messaging."
        ),
        module_path=(
            "engines.customer_journey.flow:CustomerJourneyEngine"
        ),
        composes_with=["cart_recovery", "loyalty",
                       "churn_prediction"],
        tags=["post-launch", "retention", "segmentation"],
    ))

    register_capability(Capability(
        name="audience_targeting",
        kind=CapabilityKind.ENGINE,
        description=(
            "Audience-targeting engine: builds customer "
            "segments for ad campaigns / email blasts."
        ),
        when_to_use=(
            "Use when the goal involves ad audience "
            "creation, lookalike modelling, or segmenting "
            "for marketing."
        ),
        module_path=(
            "engines.audience_targeting.flow:"
            "AudienceTargetingEngine"
        ),
        composes_with=["discount_strategy"],
        tags=["post-launch", "acquisition", "marketing"],
    ))

    # ── Demand / catalog / competition ────────────────────

    register_capability(Capability(
        name="demand_analysis",
        kind=CapabilityKind.ENGINE,
        description=(
            "Per-product demand classifier: scores demand "
            "level + trend from sales velocity + inventory "
            "turn + search signal."
        ),
        when_to_use=(
            "Use when the goal involves inventory planning, "
            "demand forecasting, identifying winners vs "
            "slow movers."
        ),
        module_path=(
            "engines.demand_analysis.flow:DemandAnalysisEngine"
        ),
        composes_with=["dynamic_pricing",
                       "product_lifecycle"],
        tags=["post-launch", "analytics", "demand"],
    ))

    register_capability(Capability(
        name="catalog",
        kind=CapabilityKind.ENGINE,
        description=(
            "Catalog management engine: identifies gaps + "
            "duplicates + classification issues across the "
            "product catalog."
        ),
        when_to_use=(
            "Use when the goal involves catalog quality, "
            "deduplication, or auditing product "
            "completeness."
        ),
        module_path="engines.catalog.flow:CatalogEngine",
        composes_with=["product_lifecycle"],
        tags=["post-launch", "catalog", "hygiene"],
    ))

    register_capability(Capability(
        name="competition_analyzer",
        kind=CapabilityKind.ENGINE,
        description=(
            "Competitor price + assortment scanner."
        ),
        when_to_use=(
            "Use when the goal involves competitive "
            "intelligence, price comparison, or matching "
            "competitor offerings."
        ),
        module_path=(
            "engines.competition_analyzer.flow:"
            "CompetitionAnalyzerEngine"
        ),
        composes_with=["dynamic_pricing"],
        tags=["post-launch", "competitive", "pricing"],
    ))
