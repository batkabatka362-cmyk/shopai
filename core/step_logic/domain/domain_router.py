"""DomainRouter — routes engine to its domain-specific logic.

Maps engine names to the right business logic module.
Falls back to generic SmartExecutor if no domain match.
"""
from __future__ import annotations
from typing import Any

from .pricing_logic import PricingLogic
from .marketing_logic import MarketingLogic
from .inventory_logic import InventoryLogic
from .seo_logic import SeoLogic
from .customer_logic import CustomerLogic
from .analytics_logic import AnalyticsLogic
from .operations_logic import OperationsLogic
from .shopify_logic import ShopifyLogic
from .growth_logic import GrowthLogic
from .content_logic import ContentLogic


# Keyword → domain mapping for engines not in explicit sets
KEYWORD_DOMAIN_MAP = {
    PricingLogic: ["price", "pricing", "discount", "coupon", "cost", "margin", "markup", "tariff", "fee", "commission", "royalty", "billing", "payment", "invoice", "revenue", "valuation", "budget"],
    MarketingLogic: ["marketing", "campaign", "ad", "ads", "social", "email", "sms", "push", "influencer", "affiliate", "brand", "promotion", "viral", "reach", "impression", "click", "conversion", "funnel", "audience", "targeting", "retarget", "media"],
    InventoryLogic: ["inventory", "stock", "warehouse", "supply", "reorder", "demand", "forecast", "procurement", "supplier", "vendor", "fulfillment", "shipping", "freight", "logistics", "delivery", "pallet", "batch"],
    SeoLogic: ["seo", "keyword", "search", "sitemap", "robots", "meta", "backlink", "rank", "serp", "crawl", "index", "canonical", "schema", "structured_data", "snippet", "hreflang", "redirect"],
    CustomerLogic: ["customer", "churn", "retention", "loyalty", "segmentation", "persona", "nps", "satisfaction", "engagement", "lifetime", "ltv", "rfm", "onboarding", "support", "ticket", "complaint", "feedback"],
    AnalyticsLogic: ["analytics", "analysis", "tracking", "metric", "kpi", "dashboard", "report", "forecast", "predict", "trend", "anomaly", "benchmark", "cohort", "attribution", "roi", "performance"],
    OperationsLogic: ["order", "shipping", "delivery", "fulfillment", "warehouse", "logistics", "route", "carrier", "return", "refund", "quality", "inspection", "tracking", "customs", "freight", "pack"],
    ContentLogic: ["content", "blog", "article", "copy", "headline", "description", "story", "creative", "video", "image", "photo", "translation", "faq", "press", "case_study", "landing", "page_builder"],
    ShopifyLogic: ["shopify", "theme", "checkout", "collection", "metafield", "store", "pos", "app_recommend"],
    GrowthLogic: ["growth", "experiment", "activation", "onboarding", "adoption", "viral", "flywheel", "north_star", "aha_moment", "mvp", "product_market"],
}


class DomainRouter:
    """Routes engines to domain-specific computation logic.

    Two-tier matching:
      1. Explicit engine sets (126 engines) — exact match
      2. Keyword matching (1000+ engines) — engine name contains domain keyword
    """

    def __init__(self) -> None:
        # ORDER MATTERS: specific domains BEFORE general ones
        # SeoLogic before MarketingLogic (both match "seo" but Seo is more specific)
        # ContentLogic before MarketingLogic (both match "content_generation")
        # CustomerLogic before AnalyticsLogic (both match "customer_analytics")
        self._domains = [
            ShopifyLogic(),      # Most specific: shopify-specific engines
            GrowthLogic(),       # Specific: growth, experiments, activation
            SeoLogic(),          # Specific: seo, keyword, sitemap, etc.
            ContentLogic(),      # Specific: content, blog, description, etc.
            CustomerLogic(),     # Specific: customer, churn, retention, etc.
            PricingLogic(),      # Specific: pricing, discount, margin, etc.
            InventoryLogic(),    # Specific: inventory, stock, warehouse, etc.
            OperationsLogic(),   # Medium: order, shipping, fulfillment, etc.
            MarketingLogic(),    # Broad: marketing, campaign, ads, etc.
            AnalyticsLogic(),    # Broadest: analytics, tracking, metric, etc.
        ]
        self._keyword_cache: dict[str, int | None] = {}

    def get_domain(self, engine_name: str):
        """Get domain logic for an engine. Two-tier: explicit → keyword."""
        # Tier 1: Explicit match
        for domain in self._domains:
            if domain.applies_to(engine_name):
                return domain

        # Tier 2: Keyword match (cached)
        if engine_name in self._keyword_cache:
            idx = self._keyword_cache[engine_name]
            return self._domains[idx] if idx is not None else None

        name_lower = engine_name.lower()
        best_domain_idx = None
        best_score = 0

        for domain_cls, keywords in KEYWORD_DOMAIN_MAP.items():
            score = sum(1 for kw in keywords if kw in name_lower)
            if score > best_score:
                best_score = score
                # Find matching domain instance
                for i, d in enumerate(self._domains):
                    if isinstance(d, domain_cls):
                        best_domain_idx = i
                        break

        # If no keyword match, use AnalyticsLogic as universal fallback
        # (it handles any numeric/list data with stats + trend detection)
        if best_domain_idx is None:
            for i, d in enumerate(self._domains):
                if isinstance(d, AnalyticsLogic):
                    best_domain_idx = i
                    break

        self._keyword_cache[engine_name] = best_domain_idx
        return self._domains[best_domain_idx] if best_domain_idx is not None else None

    def analyze(self, engine_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Run domain-specific analysis. Returns None if no domain match."""
        domain = self.get_domain(engine_name)
        if domain is None:
            return None
        return domain.analyze(data)

    def execute(self, engine_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Run domain-specific execution. Returns None if no domain match."""
        domain = self.get_domain(engine_name)
        if domain is None:
            return None
        return domain.execute(data)

    def covers(self, engine_name: str) -> bool:
        """Check if any domain covers this engine (explicit or keyword)."""
        return self.get_domain(engine_name) is not None

    def list_covered_engines(self) -> dict[str, list[str]]:
        """List all engines covered by each domain."""
        result = {}
        for domain in self._domains:
            name = type(domain).__name__
            engines = sorted(domain.__class__.__dict__.get(
                f"{name.upper().replace('LOGIC','')}_ENGINES",
                getattr(domain, [a for a in dir(domain) if a.endswith('_ENGINES')][0], set())
                if [a for a in dir(domain) if a.endswith('_ENGINES')] else set()
            ))
            result[name] = engines
        return result
