"""PreProcessor — runs real computation BEFORE model is called.

Uses Intelligence modules to enrich ALL engine data with real algorithms:
  - Products → pricing intelligence (margins, elasticity, segments)
  - Customers → recommendation intelligence (similar users, cross-sell)
  - Pages → SEO intelligence (audit scores, keyword difficulty)
  - Emails → email intelligence (subject scoring, send timing)
"""
from __future__ import annotations

import copy
import threading as _threading
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("step_logic.pre")

# Lazy-load intelligence modules
_pricing_intel = None
_pricing_intel_lock = _threading.Lock()
_rec_intel = None
_email_intel = None
_seo_intel = None


def _get_pricing():
    global _pricing_intel
    if _pricing_intel is None:
        with _pricing_intel_lock:
            if _pricing_intel is None:
                from core.intelligence.pricing_intelligence import PricingIntelligence
                _pricing_intel = PricingIntelligence()
    return _pricing_intel


def _get_rec():
    global _rec_intel
    if _rec_intel is None:
        from core.intelligence.recommendation_intelligence import RecommendationIntelligence
        _rec_intel = RecommendationIntelligence()
    return _rec_intel


def _get_email():
    global _email_intel
    if _email_intel is None:
        from core.intelligence.email_intelligence import EmailIntelligence
        _email_intel = EmailIntelligence()
    return _email_intel


def _get_seo():
    global _seo_intel
    if _seo_intel is None:
        from core.intelligence.seo_intelligence import SEOIntelligence
        _seo_intel = SEOIntelligence()
    return _seo_intel


class PreProcessor:
    """Runs business computations + intelligence injection before model call."""

    def process(self, data: dict[str, Any], engine_name: str, step_name: str) -> dict[str, Any]:
        """Pre-process data for a specific engine step. Returns new dict."""
        result = copy.deepcopy(data)

        # Always compute data quality score
        result["_data_quality"] = self._score_data_quality(data)

        # Intelligence auto-injection — enrich ANY engine data
        result = self._inject_intelligence(result, engine_name)

        # Step-specific pre-processing
        if step_name == "analyze":
            result = self._pre_analyze(result, engine_name)
        elif step_name == "execute":
            result = self._pre_execute(result, engine_name)
        elif step_name == "validate":
            result = self._pre_validate(result, engine_name)

        return result

    def _inject_intelligence(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Auto-inject intelligence into ANY engine's data based on what data is available."""
        try:
            # Products → pricing intelligence
            products = data.get("products", data.get("product_data", []))
            if isinstance(products, list) and products and isinstance(products[0], dict):
                sales = data.get("sales_history", data.get("price_history", []))
                if isinstance(sales, list) and len(sales) >= 3:
                    data["_pricing_intel"] = _get_pricing().compute_demand_curve(sales)

                comps = data.get("competitor_data", data.get("competitor_prices", []))
                if isinstance(comps, list) and comps:
                    p = products[0]
                    price = safe_float(p.get("price"))
                    cost = safe_float(p.get("cost"))
                    if price > 0 and cost > 0:
                        data["_competitor_intel"] = _get_pricing().competitor_response(price, cost, comps)

            # Customers → recommendation intelligence
            customers = data.get("customer_data", data.get("customers", []))
            purchase_history = data.get("purchase_history", data.get("orders", []))
            if isinstance(purchase_history, list) and len(purchase_history) >= 3:
                target = ""
                if isinstance(customers, list) and customers and isinstance(customers[0], dict):
                    target = str(customers[0].get("id", customers[0].get("name", "")))
                if target:
                    data["_recommendation_intel"] = _get_rec().collaborative_filter(purchase_history, target)

            # Pages → SEO intelligence
            page_data = data.get("page_data", data.get("content_data", {}))
            if isinstance(page_data, dict) and page_data.get("title"):
                data["_seo_intel"] = _get_seo().audit_page(page_data)

            # Keywords → difficulty scoring
            keywords = data.get("keywords", data.get("seed_keywords", []))
            if isinstance(keywords, list) and keywords:
                kw_diffs = []
                for kw in keywords[:5]:
                    term = kw if isinstance(kw, str) else kw.get("keyword", "") if isinstance(kw, dict) else ""
                    if term:
                        kw_diffs.append(_get_seo().keyword_difficulty(term))
                if kw_diffs:
                    data["_keyword_intel"] = kw_diffs

            # Email subject → scoring
            subject = data.get("subject_line", data.get("subject", ""))
            if isinstance(subject, str) and len(subject) > 5:
                data["_email_intel"] = _get_email().score_subject_line(subject)

            # Products + suppliers → AutoDS dropship scoring
            suppliers = data.get("suppliers", data.get("supplier_data", []))
            if isinstance(products, list) and products and isinstance(suppliers, list) and suppliers:
                from core.intelligence.autods_intelligence import AutoDSIntelligence
                ds = AutoDSIntelligence()
                dropship_scores = []
                for p in products[:5]:
                    if isinstance(p, dict):
                        score = ds.score_product_for_dropship(p, suppliers)
                        dropship_scores.append({"product": p.get("name", ""), "score": score.get("score", 0),
                                                "viable": score.get("viable", False), "margin": score.get("financials", {}).get("margin_pct", 0)})
                if dropship_scores:
                    data["_dropship_intel"] = dropship_scores

            # Financial unit economics for any product with cost data
            if isinstance(products, list) and products and isinstance(products[0], dict):
                p = products[0]
                if safe_float(p.get("cost")) > 0:
                    from core.intelligence.financial_intelligence import FinancialIntelligence
                    fi = FinancialIntelligence()
                    ad_spend = safe_float(data.get("ad_spend", data.get("marketing_spend", 0)))
                    orders_count = safe_int(data.get("order_count", data.get("total_orders", 0)))
                    data["_financial_intel"] = fi.unit_economics(p, ad_spend=ad_spend, orders=max(orders_count, 1))

            # Competitor analysis if competitor data present
            if isinstance(comps, list) and comps and isinstance(products, list) and products:
                from core.intelligence.competitor_intelligence import CompetitorIntelligence
                ci = CompetitorIntelligence()
                data["_competitor_analysis"] = ci.price_comparison(products, comps)

            # Time series → forecasting
            for ts_key in ("revenue", "sales", "orders_daily", "daily_revenue"):
                ts = data.get(ts_key, [])
                if isinstance(ts, list) and len(ts) >= 5 and isinstance(ts[0], (int, float)):
                    from core.intelligence.forecasting import Forecasting
                    data["_forecast_intel"] = Forecasting().forecast([float(v) for v in ts], periods=7)
                    break

        except Exception as exc:
            logger.warning("Intelligence injection failed (non-critical): %s", exc)

        return data

    def _pre_analyze(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Pre-compute scores and metrics for analyzer using 7-factor model."""
        products = data.get("products", data.get("product_data", []))

        if isinstance(products, list):
            # Use SmartExecutor's 7-factor scoring
            from core.step_logic.smart_executor import SmartExecutor
            se = SmartExecutor()
            scored = se._score_products(products)
            if scored:
                data["_pre_scored_products"] = scored
                data["_pre_computed"] = {
                    "avg_score": round(sum(s.get("total_score", 0) for s in scored) / len(scored), 2),
                    "viable_count": sum(1 for s in scored if s.get("viable", False)),
                    "top_margin": max((s.get("margin_pct", 0) for s in scored), default=0),
                    "high_confidence": sum(1 for s in scored if s.get("confidence") == "high"),
                }

        # Pre-compute pricing intelligence
        if "pricing_data" in data or "price" in str(data.keys()):
            data["_pricing_analysis"] = self._analyze_pricing(data)

        return data

    def _pre_execute(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Pre-compute structured context for worker."""
        # Add execution hints based on pre-analysis
        analysis = data.get("_analyze_output", data.get("analysis", {}))
        if isinstance(analysis, dict):
            score = analysis.get("score", 0)
            data["_execution_hint"] = {
                "confidence": "high" if score > 7 else "medium" if score > 4 else "low",
                "approach": "aggressive" if score > 8 else "balanced" if score > 5 else "conservative",
            }
        return data

    def _pre_validate(self, data: dict[str, Any], engine_name: str) -> dict[str, Any]:
        """Pre-compute validation checks."""
        checks = []

        # Check output completeness
        execute_output = data.get("_execute_output", data.get("execution", {}))
        if isinstance(execute_output, dict):
            if not execute_output:
                checks.append({"check": "output_empty", "passed": False})
            else:
                checks.append({"check": "output_present", "passed": True})
                checks.append({"check": "output_fields", "passed": True, "count": len(execute_output)})

        data["_pre_validation_checks"] = checks
        return data

    def _score_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Score a product — delegates to SmartExecutor's 7-factor model."""
        from core.step_logic.smart_executor import SmartExecutor
        scored = SmartExecutor()._score_products([product])
        return scored[0] if scored else dict(product)

    @staticmethod
    def _analyze_pricing(data: dict[str, Any]) -> dict[str, Any]:
        """Pre-compute pricing analysis."""
        from utils.helpers import safe_float
        prices = []
        for key in ("products", "product_data"):
            items = data.get(key, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "price" in item:
                        p = safe_float(item["price"])
                        if p > 0:
                            prices.append(p)
            elif isinstance(items, dict) and "price" in items:
                p = safe_float(items["price"])
                if p > 0:
                    prices.append(p)

        if not prices:
            return {"has_pricing": False}

        return {
            "has_pricing": True,
            "price_count": len(prices),
            "price_range": [round(min(prices), 2), round(max(prices), 2)],
            "price_avg": round(sum(prices) / len(prices), 2),
            "price_std": round((sum((p - sum(prices)/len(prices))**2 for p in prices) / len(prices)) ** 0.5, 2),
        }

    @staticmethod
    def _score_data_quality(data: dict[str, Any]) -> dict[str, Any]:
        """Score the quality/completeness of input data."""
        total_fields = len(data)
        non_empty = sum(1 for v in data.values() if v is not None and v != "" and v != [] and v != {})
        completeness = round(non_empty / total_fields, 2) if total_fields > 0 else 0

        return {
            "total_fields": total_fields,
            "non_empty_fields": non_empty,
            "completeness": completeness,
            "quality_tier": "high" if completeness > 0.8 else "medium" if completeness > 0.5 else "low",
        }
