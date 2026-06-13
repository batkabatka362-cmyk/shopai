"""Fourth batch: analytics / financial / competitive engines.

What this batch adds
--------------------
The earlier batches covered launch chain (1), post-launch
operations (2), marketing + customer-facing (3). This batch
fills the remaining gaps an autonomous merchant needs:

  - Financial: accounting, cash_flow, cashflow_simulator,
    profit_optimization, profitability_calculator,
    ltv_cac_dashboard.
  - Analytics: conversion_tracking, customer_effort_score,
    customer_behavior_simulator, forecasting,
    data_collection, data_enrichment.
  - Competitive: competitor_analysis,
    competitor_ad_intelligence, competitor_monitor,
    competitor_reaction_simulator, competitor_social.
  - Campaign + strategy: campaign_strategy.
  - Ops: dropshipping, gift_card, returns_management,
    warranty, upsell.

With this batch the registry passes ~85 entries -- enough
that the planner produces useful plans for the vast
majority of operator queries across the merchant lifecycle.
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    register_capability,
)


def register_all() -> None:
    """Idempotent batch registration."""

    # ── Financial ─────────────────────────────────────────

    register_capability(Capability(
        name="accounting",
        kind=CapabilityKind.ENGINE,
        description=(
            "Accounting engine: ledger entries, sales / "
            "tax / fee summaries, P&L assembly."
        ),
        when_to_use=(
            "Use when the goal involves bookkeeping, "
            "tax reporting, P&L generation, or "
            "month-end close."
        ),
        module_path="engines.accounting.flow:AccountingEngine",
        tags=["post-launch", "finance", "accounting",
              "reporting"],
    ))

    register_capability(Capability(
        name="cash_flow",
        kind=CapabilityKind.ENGINE,
        description=(
            "Cash flow analyser: inflows / outflows / "
            "runway / burn rate."
        ),
        when_to_use=(
            "Use when the goal involves cash flow "
            "tracking, runway computation, or pay-cycle "
            "planning."
        ),
        module_path="engines.cash_flow.flow:CashFlowEngine",
        composes_with=["cashflow_simulator", "accounting"],
        tags=["post-launch", "finance", "cash-flow"],
    ))

    register_capability(Capability(
        name="cashflow_simulator",
        kind=CapabilityKind.ENGINE,
        description=(
            "Forward-looking cash flow simulator: what-if "
            "analysis on spend / inventory / payment terms."
        ),
        when_to_use=(
            "Use when the goal involves cash flow "
            "scenarios, what-if modelling, or simulating "
            "the impact of large purchases."
        ),
        module_path=(
            "engines.cashflow_simulator.flow:"
            "CashflowSimulatorEngine"
        ),
        composes_with=["cash_flow"],
        tags=["post-launch", "finance", "simulation"],
    ))

    register_capability(Capability(
        name="profit_optimization",
        kind=CapabilityKind.ENGINE,
        description=(
            "Profit margin + COGS + fees optimisation."
        ),
        when_to_use=(
            "Use when the goal involves margin improvement, "
            "COGS reduction, or per-product profitability "
            "tuning."
        ),
        module_path=(
            "engines.profit_optimization.flow:"
            "ProfitOptimizationEngine"
        ),
        composes_with=["dynamic_pricing",
                       "profitability_calculator"],
        tags=["post-launch", "finance", "profitability"],
    ))

    register_capability(Capability(
        name="profitability_calculator",
        kind=CapabilityKind.ENGINE,
        description=(
            "Per-product / per-order profitability "
            "calculator with COGS + fee + shipping cost "
            "rollup."
        ),
        when_to_use=(
            "Use when the goal involves computing real "
            "profitability per SKU / order, identifying "
            "loss-making products, or fee-adjusted margin."
        ),
        module_path=(
            "engines.profitability_calculator.flow:"
            "ProfitabilityCalculatorEngine"
        ),
        composes_with=["profit_optimization"],
        tags=["post-launch", "finance", "profitability"],
    ))

    register_capability(Capability(
        name="ltv_cac_dashboard",
        kind=CapabilityKind.ENGINE,
        description=(
            "LTV / CAC ratio analyser: customer lifetime "
            "value vs acquisition cost by channel + cohort."
        ),
        when_to_use=(
            "Use when the goal involves LTV / CAC, channel "
            "ROI, customer-cost economics, or scaling-"
            "decision support."
        ),
        module_path=(
            "engines.ltv_cac_dashboard.flow:"
            "LtvCacDashboardEngine"
        ),
        composes_with=["cohort_analysis",
                       "audience_targeting"],
        tags=["post-launch", "analytics", "finance",
              "ltv"],
    ))

    # ── Analytics ─────────────────────────────────────────

    register_capability(Capability(
        name="conversion_tracking",
        kind=CapabilityKind.ENGINE,
        description=(
            "Funnel + conversion tracker: visitor → cart → "
            "checkout → order step-by-step rates."
        ),
        when_to_use=(
            "Use when the goal involves funnel analytics, "
            "conversion rate optimisation, or identifying "
            "drop-off points."
        ),
        module_path=(
            "engines.conversion_tracking.flow:"
            "ConversionTrackingEngine"
        ),
        composes_with=["checkout_optimizer", "ab_testing"],
        tags=["post-launch", "analytics", "conversion"],
    ))

    register_capability(Capability(
        name="customer_effort_score",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer-effort scoring: friction in support / "
            "checkout / returns measured against expected "
            "easy paths."
        ),
        when_to_use=(
            "Use when the goal involves measuring customer "
            "friction, support quality, or improving the "
            "easy-path for returns / questions."
        ),
        module_path=(
            "engines.customer_effort_score.flow:"
            "CustomerEffortScoreEngine"
        ),
        composes_with=["customer_journey",
                       "customer_support"],
        tags=["post-launch", "analytics", "support"],
    ))

    register_capability(Capability(
        name="customer_behavior_simulator",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer behaviour simulator: forward-model "
            "purchase / browse patterns for what-if planning."
        ),
        when_to_use=(
            "Use when the goal involves simulating "
            "customer reactions to price / promo / inventory "
            "changes before applying them."
        ),
        module_path=(
            "engines.customer_behavior_simulator.flow:"
            "CustomerBehaviorSimulatorEngine"
        ),
        composes_with=["audience_targeting",
                       "discount_strategy"],
        tags=["post-launch", "simulation", "analytics"],
    ))

    register_capability(Capability(
        name="forecasting",
        kind=CapabilityKind.ENGINE,
        description=(
            "Sales / inventory / cash forecasting based on "
            "historicals + seasonality + trend signal."
        ),
        when_to_use=(
            "Use when the goal involves sales forecast, "
            "demand prediction, or quarterly planning."
        ),
        module_path=(
            "engines.forecasting.flow:ForecastingEngine"
        ),
        composes_with=["demand_analysis", "cash_flow"],
        tags=["post-launch", "analytics", "forecasting"],
    ))

    register_capability(Capability(
        name="data_collection",
        kind=CapabilityKind.ENGINE,
        description=(
            "Cross-source data collector: pulls + "
            "normalises analytics signals across Shopify + "
            "Google Analytics + ad platforms."
        ),
        when_to_use=(
            "Use when the goal involves unified analytics, "
            "cross-platform data, or feeding ML pipelines."
        ),
        module_path=(
            "engines.data_collection.flow:DataCollectionEngine"
        ),
        composes_with=["data_enrichment"],
        tags=["post-launch", "data", "analytics"],
    ))

    register_capability(Capability(
        name="data_enrichment",
        kind=CapabilityKind.ENGINE,
        description=(
            "Enrichment engine: appends geo / demographic / "
            "behavioural attributes to customer / order "
            "records."
        ),
        when_to_use=(
            "Use when the goal involves customer 360, "
            "enriching CRM data, or adding context to "
            "thin records."
        ),
        module_path=(
            "engines.data_enrichment.flow:DataEnrichmentEngine"
        ),
        composes_with=["data_collection",
                       "customer_segmentation"],
        tags=["post-launch", "data", "enrichment"],
    ))

    # ── Competitive ───────────────────────────────────────

    register_capability(Capability(
        name="competitor_analysis",
        kind=CapabilityKind.ENGINE,
        description=(
            "High-level competitor benchmark: pricing / "
            "assortment / promo cadence."
        ),
        when_to_use=(
            "Use when the goal involves competitor "
            "benchmarking, market positioning research, or "
            "competitive intelligence."
        ),
        module_path=(
            "engines.competitor_analysis.flow:"
            "CompetitorAnalysisEngine"
        ),
        composes_with=["competition_analyzer",
                       "brand_positioning"],
        tags=["post-launch", "competitive", "analytics"],
    ))

    register_capability(Capability(
        name="competitor_ad_intelligence",
        kind=CapabilityKind.ENGINE,
        description=(
            "Competitor ad creative + spend intelligence."
        ),
        when_to_use=(
            "Use when the goal involves seeing what ads "
            "competitors run, their creative themes, or "
            "estimated spend."
        ),
        module_path=(
            "engines.competitor_ad_intelligence.flow:"
            "CompetitorAdIntelligenceEngine"
        ),
        composes_with=["ad_creative_generator",
                       "competitor_analysis"],
        tags=["post-launch", "competitive", "ads",
              "intelligence"],
    ))

    register_capability(Capability(
        name="competitor_monitor",
        kind=CapabilityKind.ENGINE,
        description=(
            "Continuous competitor price + assortment "
            "monitor with change-alerts."
        ),
        when_to_use=(
            "Use when the goal involves real-time "
            "competitor monitoring, change alerts, or "
            "price-match triggers."
        ),
        module_path=(
            "engines.competitor_monitor.flow:"
            "CompetitorMonitorEngine"
        ),
        composes_with=["competitor_analysis",
                       "dynamic_pricing"],
        tags=["post-launch", "competitive", "monitoring"],
    ))

    register_capability(Capability(
        name="competitor_reaction_simulator",
        kind=CapabilityKind.ENGINE,
        description=(
            "Simulates how competitors might react to a "
            "planned move (price drop / new product / promo)."
        ),
        when_to_use=(
            "Use when the goal involves anticipating "
            "competitor reaction, game-theoretic moves, or "
            "pre-mortem on a pricing change."
        ),
        module_path=(
            "engines.competitor_reaction_simulator.flow:"
            "CompetitorReactionSimulatorEngine"
        ),
        composes_with=["competitor_analysis"],
        tags=["post-launch", "competitive", "simulation"],
    ))

    register_capability(Capability(
        name="competitor_social",
        kind=CapabilityKind.ENGINE,
        description=(
            "Competitor social media activity + engagement "
            "tracker."
        ),
        when_to_use=(
            "Use when the goal involves monitoring "
            "competitor social presence or content cadence."
        ),
        module_path=(
            "engines.competitor_social.flow:"
            "CompetitorSocialEngine"
        ),
        composes_with=["competitor_analysis"],
        tags=["post-launch", "competitive", "social"],
    ))

    # ── Strategy / Ops ────────────────────────────────────

    register_capability(Capability(
        name="campaign_strategy",
        kind=CapabilityKind.ENGINE,
        description=(
            "Marketing campaign strategist: builds "
            "multi-touch campaigns across email / ads / "
            "promotions."
        ),
        when_to_use=(
            "Use when the goal involves designing a "
            "marketing campaign, multi-touch coordination, "
            "or BFCM-style event planning."
        ),
        module_path=(
            "engines.campaign_strategy.flow:"
            "CampaignStrategyEngine"
        ),
        composes_with=["discount_strategy",
                       "email_marketing",
                       "ad_creative_generator"],
        tags=["post-launch", "marketing", "strategy"],
    ))

    register_capability(Capability(
        name="dropshipping",
        kind=CapabilityKind.ENGINE,
        description=(
            "Dropshipping operations engine: supplier "
            "routing, order forwarding, margin tracking."
        ),
        when_to_use=(
            "Use when the goal involves dropshipping "
            "operations, supplier order automation, or "
            "no-stock fulfilment."
        ),
        module_path=(
            "engines.dropshipping.flow:DropshippingEngine"
        ),
        composes_with=["supplier", "order_management"],
        tags=["post-launch", "operations", "dropshipping"],
    ))

    register_capability(Capability(
        name="gift_card",
        kind=CapabilityKind.ENGINE,
        description=(
            "Gift card lifecycle engine: issue, redeem, "
            "expiry handling."
        ),
        when_to_use=(
            "Use when the goal involves gift card "
            "issuance, redemption tracking, or seasonal "
            "gift-card promotions."
        ),
        module_path="engines.gift_card.flow:GiftCardEngine",
        tags=["post-launch", "revenue", "gift-card"],
    ))

    register_capability(Capability(
        name="returns_management",
        kind=CapabilityKind.ENGINE,
        description=(
            "Return + refund workflow engine."
        ),
        when_to_use=(
            "Use when the goal involves returns processing, "
            "refund policy enforcement, or RMA workflows."
        ),
        module_path=(
            "engines.returns_management.flow:"
            "ReturnsManagementEngine"
        ),
        composes_with=["order_management"],
        tags=["post-launch", "operations", "returns"],
    ))

    register_capability(Capability(
        name="warranty",
        kind=CapabilityKind.ENGINE,
        description=(
            "Product warranty / guarantee management."
        ),
        when_to_use=(
            "Use when the goal involves warranty "
            "registration, claim handling, or guarantee "
            "policy."
        ),
        module_path="engines.warranty.flow:WarrantyEngine",
        tags=["post-launch", "operations", "warranty"],
    ))

    register_capability(Capability(
        name="upsell",
        kind=CapabilityKind.ENGINE,
        description=(
            "Upsell recommender: prompts higher-tier / "
            "premium SKU at decision points."
        ),
        when_to_use=(
            "Use when the goal involves upselling, "
            "premium-tier suggestions, or AOV "
            "improvement via upsell."
        ),
        module_path="engines.upsell.flow:UpsellEngine",
        composes_with=["cross_sell", "bundle"],
        tags=["post-launch", "revenue", "upsell"],
    ))
