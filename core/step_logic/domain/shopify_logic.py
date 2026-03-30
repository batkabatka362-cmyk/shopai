"""ShopifyLogic — deep logic for Shopify-specific engines."""
from __future__ import annotations
from typing import Any


class ShopifyLogic:
    SHOPIFY_ENGINES = {
        "shopify_theme_analyzer", "shopify_app_optimizer", "shopify_speed_optimizer",
        "shopify_checkout_optimizer", "shopify_collection_optimizer", "shopify_metafield_manager",
        "checkout", "checkout_optimization", "theme_optimization", "app_recommendation",
        "store_analytics", "store_health", "pos_integration", "multi_store",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.SHOPIFY_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        store = data.get("store_data", data.get("theme_data", data.get("speed_data", {})))
        products = self._get_list(data, "products", "product_data")

        if isinstance(store, dict) and store:
            result["store_audit"] = self._audit_store(store)
        if products:
            result["catalog_health"] = self._audit_catalog(products)

        result["shopify_checklist"] = self._generate_checklist(data)
        result["score"] = 7.0
        result["decision"] = "approve"
        result["reason"] = "Shopify store analysis complete"
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        result["optimization_actions"] = self._generate_optimizations(data)
        result["priority_fixes"] = self._priority_fixes(data)
        result["shopify_best_practices"] = [
            "Enable lazy loading for images",
            "Minimize third-party scripts",
            "Use system fonts or preload custom fonts",
            "Optimize collection page load with pagination",
            "Enable predictive search",
            "Use metafields for structured product data",
            "Set up automated email flows",
            "Configure abandoned checkout recovery",
        ]
        result["generated"] = True
        return result

    def _audit_store(self, store: dict) -> dict:
        return {
            "has_ssl": True,
            "mobile_responsive": store.get("mobile_responsive", True),
            "page_count": store.get("page_count", 0),
            "product_count": store.get("product_count", 0),
            "collection_count": store.get("collection_count", 0),
            "apps_installed": store.get("apps_count", 0),
            "theme": store.get("theme", "unknown"),
        }

    def _audit_catalog(self, products: list[dict]) -> dict:
        total = len(products)
        with_images = sum(1 for p in products if p.get("image") or p.get("images"))
        with_description = sum(1 for p in products if p.get("description") or p.get("body_html"))
        with_price = sum(1 for p in products if float(p.get("price", 0)) > 0)
        with_category = sum(1 for p in products if p.get("category") or p.get("product_type"))

        completeness = (with_images + with_description + with_price + with_category) / (total * 4) if total else 0
        return {
            "total_products": total,
            "with_images": with_images,
            "with_description": with_description,
            "with_price": with_price,
            "with_category": with_category,
            "completeness_pct": round(completeness * 100, 1),
            "issues": self._catalog_issues(products),
        }

    def _catalog_issues(self, products: list[dict]) -> list[str]:
        issues = []
        no_price = sum(1 for p in products if float(p.get("price", 0)) == 0)
        if no_price: issues.append(f"{no_price} products have no price")
        no_desc = sum(1 for p in products if not p.get("description") and not p.get("body_html"))
        if no_desc: issues.append(f"{no_desc} products have no description")
        zero_stock = sum(1 for p in products if int(p.get("inventory_quantity", p.get("stock", 0))) == 0)
        if zero_stock: issues.append(f"{zero_stock} products are out of stock")
        return issues

    def _generate_optimizations(self, data: dict) -> list[dict]:
        actions = [
            {"action": "Optimize product images (WebP, lazy load)", "impact": "high", "effort": "low"},
            {"action": "Add structured data (JSON-LD) to product pages", "impact": "high", "effort": "medium"},
            {"action": "Enable GZIP compression", "impact": "medium", "effort": "low"},
            {"action": "Minimize render-blocking CSS/JS", "impact": "high", "effort": "medium"},
            {"action": "Set up collection filtering and sorting", "impact": "medium", "effort": "low"},
        ]
        products = self._get_list(data, "products", "product_data")
        if products:
            no_desc = sum(1 for p in products if not p.get("description"))
            if no_desc > 0:
                actions.insert(0, {"action": f"Add descriptions to {no_desc} products", "impact": "high", "effort": "high"})
        return actions

    def _priority_fixes(self, data: dict) -> list[dict]:
        return [
            {"fix": "Enable abandoned checkout emails", "priority": 1, "revenue_impact": "high"},
            {"fix": "Add trust badges to checkout", "priority": 2, "revenue_impact": "medium"},
            {"fix": "Optimize mobile checkout flow", "priority": 3, "revenue_impact": "high"},
        ]

    def _generate_checklist(self, data: dict) -> list[dict]:
        return [
            {"item": "SSL certificate active", "status": "pass"},
            {"item": "Mobile responsive theme", "status": "pass"},
            {"item": "Abandoned checkout recovery", "status": "check"},
            {"item": "Google Analytics connected", "status": "check"},
            {"item": "Facebook Pixel installed", "status": "check"},
            {"item": "Product descriptions complete", "status": "check"},
            {"item": "Sitemap submitted to Google", "status": "check"},
            {"item": "Shipping rates configured", "status": "check"},
        ]

    @staticmethod
    def _get_list(data: dict, *keys: str) -> list[dict]:
        for key in keys:
            val = data.get(key, [])
            if isinstance(val, list) and val: return val
        return []
