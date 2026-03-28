"""Engine Registry — maps all 75 engine names to their classes.

Single source of truth for engine lookup. Used by the orchestrator
to instantiate and route tasks to engines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engines.base import BaseEngine

# Lazy imports to avoid circular dependencies and speed up startup
_ENGINE_MAP: dict[str, str] = {
    "product_selection": "engines.product_selection",
    "product_scoring": "engines.product_scoring",
    "product_validation": "engines.product_validation",
    "catalog": "engines.catalog",
    "inventory": "engines.inventory",
    "supplier": "engines.supplier",
    "market_research": "engines.market_research",
    "demand_analysis": "engines.demand_analysis",
    "competitor_analysis": "engines.competitor_analysis",
    "forecasting": "engines.forecasting",
    "pricing": "engines.pricing",
    "dynamic_pricing": "engines.dynamic_pricing",
    "monetization": "engines.monetization",
    "content_generation": "engines.content_generation",
    "creative_generation": "engines.creative_generation",
    "media": "engines.media",
    "storytelling": "engines.storytelling",
    "branding": "engines.branding",
    "marketing": "engines.marketing",
    "campaign": "engines.campaign",
    "ads": "engines.ads",
    "traffic": "engines.traffic",
    "seo": "engines.seo",
    "virality": "engines.virality",
    "funnel": "engines.funnel",
    "checkout": "engines.checkout",
    "conversion": "engines.conversion",
    "engagement": "engines.engagement",
    "retention": "engines.retention",
    "loyalty": "engines.loyalty",
    "referral": "engines.referral",
    "personalization": "engines.personalization",
    "recommendation": "engines.recommendation",
    "psychology": "engines.psychology",
    "persuasion": "engines.persuasion",
    "analytics": "engines.analytics",
    "financial": "engines.financial",
    "revenue": "engines.revenue",
    "profit": "engines.profit",
    "cost": "engines.cost",
    "investment": "engines.investment",
    "risk": "engines.risk",
    "logistics": "engines.logistics",
    "localization": "engines.localization",
    "multi_store": "engines.multi_store",
    "ecosystem": "engines.ecosystem",
    "automation": "engines.automation",
    "workflow": "engines.workflow",
    "scheduling": "engines.scheduling",
    "orchestration": "engines.orchestration",
    "execution": "engines.execution",
    "decision": "engines.decision",
    "reasoning": "engines.reasoning",
    "knowledge": "engines.knowledge",
    "planning": "engines.planning",
    "strategy": "engines.strategy",
    "simulation": "engines.simulation",
    "monitoring": "engines.monitoring",
    "anomaly_detection": "engines.anomaly_detection",
    "debugging": "engines.debugging",
    "logging": "engines.logging",
    "security": "engines.security",
    "fraud": "engines.fraud",
    "compliance": "engines.compliance",
    "governance": "engines.governance",
    "growth": "engines.growth",
    "growth_loop": "engines.growth_loop",
    "scaling": "engines.scaling",
    "ux": "engines.ux",
    "experimentation": "engines.experimentation",
    "innovation": "engines.innovation",
    "r_and_d": "engines.r_and_d",
    "meta_learning": "engines.meta_learning",
    "self_improvement": "engines.self_improvement",
    "self_evolution": "engines.self_evolution",
}

_engine_cache: dict[str, BaseEngine] = {}


def get_engine(name: str) -> BaseEngine:
    """Get an engine instance by name (cached)."""
    if name in _engine_cache:
        return _engine_cache[name]

    if name not in _ENGINE_MAP:
        raise KeyError(f"Unknown engine: {name}")

    import importlib
    module = importlib.import_module(_ENGINE_MAP[name])

    # Convention: class name is CamelCase of engine name + "Engine"
    words = name.split("_")
    class_name = "".join(w.capitalize() for w in words) + "Engine"
    engine_class = getattr(module, class_name)
    instance = engine_class()
    _engine_cache[name] = instance
    return instance


def list_engines() -> list[str]:
    """Return all registered engine names."""
    return sorted(_ENGINE_MAP.keys())


def engine_count() -> int:
    """Return total number of registered engines."""
    return len(_ENGINE_MAP)
