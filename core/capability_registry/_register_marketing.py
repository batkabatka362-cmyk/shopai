"""Third batch: marketing / content / ops / customer-facing
engines.

What this batch adds
--------------------
The first batch (launch chain) was about making a store
LAUNCHABLE. The second batch (engines) was about engines
that operate on a launched store to EARN REVENUE. This third
batch is the broader operator surface -- the engines that
diverse goal queries ("email campaign", "ad creative", "find
suppliers", "checkout optimisation") need to surface.

Coverage:
  - Acquisition: ad_creative_generator, email_marketing,
    audience_targeting (already in batch 2),
    trend_detection, trend_discovery.
  - Conversion: ab_testing, checkout_optimizer, chatbot.
  - Content: content_generation, brand_voice_enforcer,
    brand_visual, brand_positioning.
  - Customer-facing: customer_service, customer_support,
    customer_segmentation, review_management.
  - Operations: inventory, order_management, order_quality,
    shipping_optimization, fraud_detection, subscription.
  - Supply: supplier, supplier_communication,
    supplier_discovery, wholesale_b2b.
  - Reporting: email_reporter.

Each registration uses the same schema as the previous
batches. ``composes_with`` chains are conservative -- they
encode only relationships I'm confident about; the planner
walks one hop so over-claiming would surface noise.
"""
from __future__ import annotations

from .registry import (
    Capability,
    CapabilityKind,
    register_capability,
)


def register_all() -> None:
    """Idempotent batch registration."""

    # ── Acquisition ───────────────────────────────────────

    register_capability(Capability(
        name="ad_creative_generator",
        kind=CapabilityKind.ENGINE,
        description=(
            "Generates ad creative (copy + image prompts) "
            "tailored to product + audience + channel."
        ),
        when_to_use=(
            "Use when the goal involves creating Facebook / "
            "Instagram / TikTok / Google ad creative, "
            "writing ad copy, or producing image prompts "
            "for an ad campaign."
        ),
        module_path=(
            "engines.ad_creative_generator.flow:"
            "AdCreativeGeneratorEngine"
        ),
        composes_with=["audience_targeting",
                       "brand_voice_enforcer"],
        tags=["post-launch", "marketing", "acquisition",
              "ads", "creative"],
    ))

    register_capability(Capability(
        name="email_marketing",
        kind=CapabilityKind.ENGINE,
        description=(
            "Email campaign engine: subject lines, body "
            "copy, send-time optimisation, segment-aware "
            "messaging."
        ),
        when_to_use=(
            "Use when the goal involves email campaigns, "
            "newsletter content, transactional email copy, "
            "or send-time optimisation."
        ),
        module_path=(
            "engines.email_marketing.flow:"
            "EmailMarketingEngine"
        ),
        composes_with=["audience_targeting",
                       "customer_journey",
                       "brand_voice_enforcer"],
        tags=["post-launch", "marketing", "acquisition",
              "retention", "email"],
    ))

    register_capability(Capability(
        name="trend_detection",
        kind=CapabilityKind.ENGINE,
        description=(
            "Detects emerging product / category trends "
            "from search + social + sales signal."
        ),
        when_to_use=(
            "Use when the goal involves spotting rising "
            "demand, identifying trending products, or "
            "feeding catalog expansion decisions."
        ),
        module_path=(
            "engines.trend_detection.flow:TrendDetectionEngine"
        ),
        composes_with=["demand_analysis",
                       "trend_discovery"],
        tags=["post-launch", "analytics", "trends",
              "acquisition"],
    ))

    register_capability(Capability(
        name="trend_discovery",
        kind=CapabilityKind.ENGINE,
        description=(
            "Discovers new product niches / categories the "
            "store could enter based on cross-store + "
            "external trend signal."
        ),
        when_to_use=(
            "Use when the goal involves exploring new "
            "niches, expanding catalog, or auto-research."
        ),
        module_path=(
            "engines.trend_discovery.flow:TrendDiscoveryEngine"
        ),
        composes_with=["trend_detection",
                       "competition_analyzer"],
        tags=["post-launch", "research", "trends",
              "acquisition"],
    ))

    # ── Conversion ────────────────────────────────────────

    register_capability(Capability(
        name="ab_testing",
        kind=CapabilityKind.ENGINE,
        description=(
            "A/B test design + statistical significance "
            "scorer. Designs variants, computes sample size, "
            "reports winners."
        ),
        when_to_use=(
            "Use when the goal involves A/B testing pages "
            "/ pricing / creative / landing copy, or "
            "deciding when to declare a winner."
        ),
        module_path="engines.ab_testing.flow:ABTestingEngine",
        tags=["post-launch", "conversion", "testing"],
    ))

    register_capability(Capability(
        name="checkout_optimizer",
        kind=CapabilityKind.ENGINE,
        description=(
            "Identifies + scores checkout-funnel friction "
            "(shipping reveal, account requirement, "
            "trust signals, payment methods)."
        ),
        when_to_use=(
            "Use when the goal involves reducing checkout "
            "abandonment, improving conversion at the "
            "cart-to-purchase step, or auditing checkout UX."
        ),
        module_path=(
            "engines.checkout_optimizer.flow:"
            "CheckoutOptimizerEngine"
        ),
        composes_with=["cart_recovery", "ab_testing"],
        tags=["post-launch", "conversion", "checkout",
              "revenue"],
    ))

    register_capability(Capability(
        name="chatbot",
        kind=CapabilityKind.ENGINE,
        description=(
            "Conversational chatbot for storefront support "
            "(pre-purchase questions, returns, sizing)."
        ),
        when_to_use=(
            "Use when the goal involves customer chat / "
            "support automation, pre-purchase Q&A, or "
            "deflecting support tickets."
        ),
        module_path="engines.chatbot.flow:ChatbotEngine",
        composes_with=["customer_service",
                       "customer_support"],
        tags=["post-launch", "conversion", "support",
              "automation"],
    ))

    # ── Content + brand ───────────────────────────────────

    register_capability(Capability(
        name="content_generation",
        kind=CapabilityKind.ENGINE,
        description=(
            "Long-form content generator: blog posts, "
            "buyer's guides, comparison articles."
        ),
        when_to_use=(
            "Use when the goal involves writing blog "
            "posts, SEO articles, content marketing, or "
            "buyer guides."
        ),
        module_path=(
            "engines.content_generation.flow:"
            "ContentGenerationEngine"
        ),
        composes_with=["brand_voice_enforcer",
                       "seo_meta_enricher"],
        tags=["post-launch", "content", "seo"],
    ))

    register_capability(Capability(
        name="brand_voice_enforcer",
        kind=CapabilityKind.ENGINE,
        description=(
            "Audits generated copy against the store's "
            "brand voice guidelines + rewrites to match."
        ),
        when_to_use=(
            "Use when the goal involves brand voice "
            "consistency, tone correction, or before "
            "publishing AI-generated copy."
        ),
        module_path=(
            "engines.brand_voice_enforcer.flow:"
            "BrandVoiceEnforcerEngine"
        ),
        composes_with=["content_generation",
                       "email_marketing"],
        tags=["post-launch", "content", "brand"],
    ))

    register_capability(Capability(
        name="brand_visual",
        kind=CapabilityKind.ENGINE,
        description=(
            "Brand visual identity engine: color palette, "
            "type pairings, image style recommendations."
        ),
        when_to_use=(
            "Use when the goal involves brand visual "
            "identity, color palette decisions, or visual "
            "consistency across assets."
        ),
        module_path=(
            "engines.brand_visual.flow:BrandVisualEngine"
        ),
        composes_with=["store_design_engine"],
        tags=["post-launch", "brand", "design"],
    ))

    register_capability(Capability(
        name="brand_positioning",
        kind=CapabilityKind.ENGINE,
        description=(
            "Brand positioning strategist: defines + "
            "validates the brand's market position vs "
            "competitors."
        ),
        when_to_use=(
            "Use when the goal involves brand positioning, "
            "messaging hierarchy, or competitive "
            "differentiation."
        ),
        module_path=(
            "engines.brand_positioning.flow:"
            "BrandPositioningEngine"
        ),
        composes_with=["competition_analyzer",
                       "brand_voice_enforcer"],
        tags=["post-launch", "brand", "strategy"],
    ))

    # ── Customer-facing ───────────────────────────────────

    register_capability(Capability(
        name="customer_service",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer service ticket triage + suggested "
            "response generator."
        ),
        when_to_use=(
            "Use when the goal involves handling customer "
            "service tickets, auto-replying to common "
            "questions, or routing complex issues."
        ),
        module_path=(
            "engines.customer_service.flow:"
            "CustomerServiceEngine"
        ),
        composes_with=["chatbot", "customer_support"],
        tags=["post-launch", "support"],
    ))

    register_capability(Capability(
        name="customer_support",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer support workflow + SLA tracker."
        ),
        when_to_use=(
            "Use when the goal involves SLA tracking, "
            "support workload management, or escalation "
            "rules."
        ),
        module_path=(
            "engines.customer_support.flow:"
            "CustomerSupportEngine"
        ),
        composes_with=["customer_service"],
        tags=["post-launch", "support", "operations"],
    ))

    register_capability(Capability(
        name="customer_segmentation",
        kind=CapabilityKind.ENGINE,
        description=(
            "Customer segmentation engine: behavioural + "
            "demographic + value-based segments."
        ),
        when_to_use=(
            "Use when the goal involves segmenting "
            "customers for targeted marketing, "
            "personalisation, or lifecycle stages."
        ),
        module_path=(
            "engines.customer_segmentation.flow:"
            "CustomerSegmentationEngine"
        ),
        composes_with=["audience_targeting",
                       "customer_journey",
                       "email_marketing"],
        tags=["post-launch", "segmentation", "marketing"],
    ))

    register_capability(Capability(
        name="review_management",
        kind=CapabilityKind.ENGINE,
        description=(
            "Product review + rating management: solicits, "
            "moderates, surfaces social proof."
        ),
        when_to_use=(
            "Use when the goal involves collecting + "
            "displaying reviews, responding to ratings, "
            "or building social proof."
        ),
        module_path=(
            "engines.review_management.flow:"
            "ReviewManagementEngine"
        ),
        tags=["post-launch", "conversion", "trust"],
    ))

    # ── Operations ────────────────────────────────────────

    register_capability(Capability(
        name="inventory",
        kind=CapabilityKind.ENGINE,
        description=(
            "Inventory engine: stock levels, reorder "
            "points, stockout risk."
        ),
        when_to_use=(
            "Use when the goal involves inventory "
            "management, reorder triggers, stockout "
            "prevention, or fulfillment-driven decisions."
        ),
        module_path="engines.inventory.flow:InventoryEngine",
        composes_with=["demand_analysis",
                       "product_lifecycle"],
        tags=["post-launch", "operations", "inventory"],
    ))

    register_capability(Capability(
        name="order_management",
        kind=CapabilityKind.ENGINE,
        description=(
            "Order management: status flow, exception "
            "handling, fulfilment routing."
        ),
        when_to_use=(
            "Use when the goal involves order processing, "
            "fulfilment routing, or order exception "
            "handling."
        ),
        module_path=(
            "engines.order_management.flow:"
            "OrderManagementEngine"
        ),
        composes_with=["shipping_optimization",
                       "fraud_detection"],
        tags=["post-launch", "operations", "orders"],
    ))

    register_capability(Capability(
        name="order_quality",
        kind=CapabilityKind.ENGINE,
        description=(
            "Order quality scoring: identifies high-risk / "
            "high-value orders for prioritisation."
        ),
        when_to_use=(
            "Use when the goal involves order risk "
            "scoring, VIP order flagging, or fulfilment "
            "prioritisation."
        ),
        module_path=(
            "engines.order_quality.flow:OrderQualityEngine"
        ),
        composes_with=["order_management",
                       "fraud_detection"],
        tags=["post-launch", "operations", "orders",
              "risk"],
    ))

    register_capability(Capability(
        name="shipping_optimization",
        kind=CapabilityKind.ENGINE,
        description=(
            "Shipping carrier + zone optimisation."
        ),
        when_to_use=(
            "Use when the goal involves shipping cost "
            "optimisation, carrier selection, or zone "
            "configuration."
        ),
        module_path=(
            "engines.shipping_optimization.flow:"
            "ShippingOptimizationEngine"
        ),
        composes_with=["order_management"],
        tags=["post-launch", "operations", "shipping"],
    ))

    register_capability(Capability(
        name="fraud_detection",
        kind=CapabilityKind.ENGINE,
        description=(
            "Order fraud risk scorer."
        ),
        when_to_use=(
            "Use when the goal involves detecting "
            "fraudulent orders, chargeback prevention, or "
            "risk-based holds."
        ),
        module_path=(
            "engines.fraud_detection.flow:FraudDetectionEngine"
        ),
        composes_with=["order_quality", "order_management"],
        tags=["post-launch", "operations", "risk", "fraud"],
    ))

    register_capability(Capability(
        name="subscription",
        kind=CapabilityKind.ENGINE,
        description=(
            "Subscription / recurring-revenue engine: plan "
            "design, churn handling, billing cycles."
        ),
        when_to_use=(
            "Use when the goal involves subscription "
            "products, recurring billing, or "
            "subscription churn."
        ),
        module_path=(
            "engines.subscription.flow:SubscriptionEngine"
        ),
        composes_with=["churn_prediction", "loyalty"],
        tags=["post-launch", "revenue", "recurring"],
    ))

    # ── Supply ───────────────────────────────────────────

    register_capability(Capability(
        name="supplier",
        kind=CapabilityKind.ENGINE,
        description=(
            "Supplier evaluation + performance tracking."
        ),
        when_to_use=(
            "Use when the goal involves supplier "
            "selection, performance benchmarking, or "
            "vendor management."
        ),
        module_path="engines.supplier.flow:SupplierEngine",
        composes_with=["supplier_discovery",
                       "supplier_communication"],
        tags=["post-launch", "operations", "supply"],
    ))

    register_capability(Capability(
        name="supplier_discovery",
        kind=CapabilityKind.ENGINE,
        description=(
            "Discover new suppliers from B2B sources + "
            "marketplaces matching the store's catalog."
        ),
        when_to_use=(
            "Use when the goal involves finding new "
            "suppliers, sourcing products, or evaluating "
            "dropshipping partners."
        ),
        module_path=(
            "engines.supplier_discovery.flow:"
            "SupplierDiscoveryEngine"
        ),
        composes_with=["supplier", "trend_discovery"],
        tags=["post-launch", "operations", "supply",
              "sourcing"],
    ))

    register_capability(Capability(
        name="supplier_communication",
        kind=CapabilityKind.ENGINE,
        description=(
            "Supplier outreach + negotiation copy + "
            "follow-up scheduling."
        ),
        when_to_use=(
            "Use when the goal involves emailing "
            "suppliers, negotiating terms, or managing "
            "supplier relationships."
        ),
        module_path=(
            "engines.supplier_communication.flow:"
            "SupplierCommunicationEngine"
        ),
        composes_with=["supplier", "email_marketing"],
        tags=["post-launch", "operations", "supply",
              "communication"],
    ))

    register_capability(Capability(
        name="wholesale_b2b",
        kind=CapabilityKind.ENGINE,
        description=(
            "B2B wholesale engine: bulk pricing tiers, "
            "trade-account management, B2B-specific "
            "discounts."
        ),
        when_to_use=(
            "Use when the goal involves B2B sales, "
            "wholesale pricing tiers, or trade accounts."
        ),
        module_path=(
            "engines.wholesale_b2b.flow:WholesaleB2bEngine"
        ),
        composes_with=["discount_strategy"],
        tags=["post-launch", "revenue", "b2b", "wholesale"],
    ))

    # ── Reporting ─────────────────────────────────────────

    register_capability(Capability(
        name="email_reporter",
        kind=CapabilityKind.ENGINE,
        description=(
            "Email-based reporting + digest generator."
        ),
        when_to_use=(
            "Use when the goal involves generating "
            "operator email digests, performance reports, "
            "or scheduled email summaries."
        ),
        module_path=(
            "engines.email_reporter.flow:EmailReporterEngine"
        ),
        tags=["post-launch", "reporting", "ops"],
    ))
