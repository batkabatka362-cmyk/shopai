"""Engine Registry — maps engine names to their module paths.

Only includes engines with real implementations (70+ lines of code).
Stub/placeholder engines have been removed.

69 real engines + base framework.
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
