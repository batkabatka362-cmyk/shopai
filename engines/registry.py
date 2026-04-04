"""Engine Registry — maps engine names to their module paths.

Includes all engines: production-ready (flow.py pattern), original (modules/),
and stub (BaseEngine). 86 engines + base framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engines.base import BaseEngine

# Engine name → module path (only engines that actually exist)
_ENGINE_MAP: dict[str, str] = {
    # Product & Catalog
    "product_selection": "engines.product_selection",
    "product_scoring": "engines.product_scoring",
    "product_validation": "engines.product_validation",
    "product_description": "engines.product_description",
    "product_lifecycle": "engines.product_lifecycle",
    "product_optimization": "engines.product_optimization",
    "product_ranking": "engines.product_ranking",
    "catalog": "engines.catalog",
    "image_optimization": "engines.image_optimization",

    # Inventory & Supply Chain
    "inventory": "engines.inventory",
    "supplier": "engines.supplier",
    "stock_prediction": "engines.stock_prediction",
    "shipping_optimization": "engines.shipping_optimization",
    "returns_management": "engines.returns_management",

    # Pricing & Revenue
    "pricing": "engines.pricing",
    "dynamic_pricing": "engines.dynamic_pricing",
    "price_elasticity": "engines.price_elasticity",
    "discount_strategy": "engines.discount_strategy",
    "monetization": "engines.monetization",
    "payment_optimization": "engines.payment_optimization",
    "financial": "engines.financial",

    # Marketing & Campaigns
    "email_marketing": "engines.email_marketing",
    "social_media": "engines.social_media",
    "influencer": "engines.influencer",
    "affiliate": "engines.affiliate",
    "video_marketing": "engines.video_marketing",
    "content_generation": "engines.content_generation",
    "landing_page": "engines.landing_page",

    # Customer Intelligence
    "customer_segmentation": "engines.customer_segmentation",
    "customer_support": "engines.customer_support",
    "audience_targeting": "engines.audience_targeting",
    "churn_prediction": "engines.churn_prediction",
    "sentiment_analysis": "engines.sentiment_analysis",
    "review_management": "engines.review_management",

    # Conversion & Sales
    "ab_testing": "engines.ab_testing",
    "cart_recovery": "engines.cart_recovery",
    "bundle": "engines.bundle",
    "upsell": "engines.upsell",
    "cross_sell": "engines.cross_sell",
    "search_optimization": "engines.search_optimization",

    # Analytics & Data
    "demand_analysis": "engines.demand_analysis",
    "competitor_analysis": "engines.competitor_analysis",
    "forecasting": "engines.forecasting",
    "trend_detection": "engines.trend_detection",
    "opportunity_detection": "engines.opportunity_detection",
    "opportunity_scoring": "engines.opportunity_scoring",
    "kpi_tracking": "engines.kpi_tracking",
    "data_collection": "engines.data_collection",
    "data_enrichment": "engines.data_enrichment",
    "behavioral_data": "engines.behavioral_data",
    "conversion_tracking": "engines.conversion_tracking",
    "event_tracking": "engines.event_tracking",
    "user_tracking": "engines.user_tracking",

    # Learning & Feedback
    "feedback_collection": "engines.feedback_collection",
    "feedback_processing": "engines.feedback_processing",
    "learning_loop": "engines.learning_loop",

    # Customer Experience
    "chatbot": "engines.chatbot",
    "notification": "engines.notification",
    "subscription": "engines.subscription",
    "gift_card": "engines.gift_card",
    "warranty": "engines.warranty",
    "wishlist": "engines.wishlist",
    "marketplace": "engines.marketplace",
    "tag_management": "engines.tag_management",

    # Autonomous
    "autonomous_control": "engines.autonomous_control",
    "autonomous_decision": "engines.autonomous_decision",
    "autonomous_execution": "engines.autonomous_execution",
    "orchestration": "engines.orchestration",
    "infinite_scaling": "engines.infinite_scaling",

    # ── P0 Critical Engines (NEW — flow.py pattern) ──────────────

    # Operations
    "order_management": "engines.order_management",
    "fraud_detection": "engines.fraud_detection",
    "webhook_handler": "engines.webhook_handler",

    # Finance
    "tax_engine": "engines.tax_engine",
    "accounting": "engines.accounting",
    "cash_flow": "engines.cash_flow",

    # Customer
    "customer_service": "engines.customer_service",

    # Infrastructure
    "backup_recovery": "engines.backup_recovery",

    # Product
    "product_variant": "engines.product_variant",

    # ── Previously Unregistered Engines (flow.py / modules pattern) ──

    # Intelligence & Learning
    "auto_research": "engines.auto_research",
    "execution_intelligence": "engines.execution_intelligence",
    "global_brain": "engines.global_brain",
    "meta_governance": "engines.meta_governance",
    "profit_optimization": "engines.profit_optimization",
    "simulation_lab": "engines.simulation_lab",
    "time_intelligence": "engines.time_intelligence",

    # Original Module-based Engines
    "competition_analyzer": "engines.competition_analyzer",
    "demand_estimator": "engines.demand_estimator",
    "market_research": "engines.market_research",
    "product_filter": "engines.product_filter",
    "product_risk": "engines.product_risk",
    "profitability_calculator": "engines.profitability_calculator",
    "selection_decision": "engines.selection_decision",
    "selection_reasoning": "engines.selection_reasoning",
    "supplier_discovery": "engines.supplier_discovery",
    "trend_discovery": "engines.trend_discovery",

    # ── P1 Engines (flow.py pattern) ────────────────────────────
    "store_design": "engines.store_design",
    "legal_document": "engines.legal_document",
    "checkout_optimizer": "engines.checkout_optimizer",
    "browse_recovery": "engines.browse_recovery",
    "loyalty": "engines.loyalty",
    "supplier_communication": "engines.supplier_communication",
    "competitor_monitor": "engines.competitor_monitor",

    # ── P8 Growth Engines (flow.py pattern) ─────────────────────
    "international_expansion": "engines.international_expansion",
    "wholesale_b2b": "engines.wholesale_b2b",
    "dropshipping": "engines.dropshipping",

    # ── P9 Customer Deep Analytics (flow.py pattern) ────────────
    "cohort_analysis": "engines.cohort_analysis",
    "nps_engine": "engines.nps_engine",
    "ltv_cac_dashboard": "engines.ltv_cac_dashboard",

    # ── P10 Competitive Intelligence (flow.py pattern) ──────────
    "competitor_ad_intelligence": "engines.competitor_ad_intelligence",
    "competitor_social": "engines.competitor_social",

    # ── P11 Operational (flow.py pattern) ───────────────────────
    "sop_generator": "engines.sop_generator",
    "order_quality": "engines.order_quality",

    # ── Final Engines (flow.py pattern) ─────────────────────────
    "customer_effort_score": "engines.customer_effort_score",
    "team_task_manager": "engines.team_task_manager",
    "customer_journey": "engines.customer_journey",
    "performance_monitor": "engines.performance_monitor",
    "security_monitor": "engines.security_monitor",

    # ── Simulation Engines (flow.py pattern) ───────────────────
    "market_simulator": "engines.market_simulator",
    "competitor_reaction_simulator": "engines.competitor_reaction_simulator",
    "cashflow_simulator": "engines.cashflow_simulator",
    "customer_behavior_simulator": "engines.customer_behavior_simulator",

    # ── Strategy Engines (flow.py pattern) ─────────────────────
    "campaign_strategy": "engines.campaign_strategy",
    "workflow_builder": "engines.workflow_builder",

    # ── Reporting Engines (flow.py pattern) ────────────────────
    "report_dashboard": "engines.report_dashboard",
    "email_reporter": "engines.email_reporter",
}

# Cache for instantiated engines
_cache: dict[str, "BaseEngine"] = {}


def get_engine(name: str) -> "BaseEngine | None":
    """Get an engine instance by name (lazy-loaded, cached)."""
    if name in _cache:
        return _cache[name]

    module_path = _ENGINE_MAP.get(name)
    if module_path is None:
        return None

    try:
        import importlib
        mod = importlib.import_module(module_path)
        # Find the engine class (first class ending with 'Engine')
        engine_cls = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if isinstance(attr, type) and attr_name.endswith("Engine") and attr_name != "BaseEngine":
                engine_cls = attr
                break

        if engine_cls is None:
            return None

        engine = engine_cls()
        _cache[name] = engine
        return engine

    except Exception:
        return None


def list_engines() -> list[str]:
    """List all registered engine names."""
    return sorted(_ENGINE_MAP.keys())


def engine_count() -> int:
    """Return the number of registered engines."""
    return len(_ENGINE_MAP)


def is_registered(name: str) -> bool:
    """Check if an engine is registered."""
    return name in _ENGINE_MAP


def clear_cache() -> None:
    """Clear the engine instance cache."""
    _cache.clear()
