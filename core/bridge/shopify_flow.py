"""ShopifyFlow — complete end-to-end Shopify automation flows.

Real flows that connect Shopify data → engines → actions → back to Shopify.
Each flow is a complete business operation, not just engine calls.
"""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id
from core.bridge.shopify_bridge import ShopifyBridge
from core.bridge.execution_bridge import ExecutionBridge

logger = get_logger("bridge.shopify_flow")


class ShopifyFlow:
    """End-to-end Shopify automation flows."""

    def __init__(self, shop_url: str = "", api_key: str = "") -> None:
        self._shopify = ShopifyBridge(shop_url, api_key)
        self._execution = ExecutionBridge()

    def analyze_store(self) -> dict[str, Any]:
        """Full store analysis: products + orders + customers → insights."""
        flow_id = generate_id("flow")
        start = time.monotonic()

        # Fetch all data
        products = self._shopify.fetch_products()
        orders = self._shopify.fetch_orders()
        customers = self._shopify.fetch_customers()

        # Run engines
        from engines.registry import get_engine
        from engines.base.engine_types import EngineInput

        results = {}

        # Product analysis
        e = get_engine("product_selection")
        out = e.run(EngineInput(task_id=f"{flow_id}_products", engine_name="product_selection",
                                 data={"products": products, "criteria": {"min_margin": 20}}))
        results["product_analysis"] = {
            "total_products": len(products),
            "selected": len(out.result.get("selected_products", [])),
            "top_product": out.result.get("selection_summary", {}).get("top_product"),
            "scored_products": out.result.get("scored_products", [])[:5],
        }

        # Pricing analysis
        e2 = get_engine("pricing")
        out2 = e2.run(EngineInput(task_id=f"{flow_id}_pricing", engine_name="pricing",
                                   data={"products": products}))
        results["pricing_analysis"] = {
            "price_range": out2.result.get("price_analysis", {}),
            "margins": out2.result.get("margin_analysis", {}),
            "opportunities": out2.result.get("pricing_opportunities", [])[:5],
            "recommendations": out2.result.get("pricing_recommendations", [])[:3],
        }

        # Customer analysis
        e3 = get_engine("customer_segmentation")
        out3 = e3.run(EngineInput(task_id=f"{flow_id}_customers", engine_name="customer_segmentation",
                                   data={"customer_data": customers, "segmentation_criteria": {}}))
        results["customer_analysis"] = {
            "total_customers": len(customers),
            "segments": out3.result.get("rfm_segments", {}),
            "churn_risks": out3.result.get("churn_risks", [])[:5],
            "high_value": out3.result.get("high_value", [])[:5],
        }

        # Revenue from orders
        total_revenue = sum(float(o.get("total", 0)) for o in orders)
        avg_order = total_revenue / len(orders) if orders else 0
        results["order_analysis"] = {
            "total_orders": len(orders),
            "total_revenue": round(total_revenue, 2),
            "avg_order_value": round(avg_order, 2),
        }

        elapsed = time.monotonic() - start

        return {
            "flow_id": flow_id,
            "flow": "analyze_store",
            "elapsed_seconds": round(elapsed, 3),
            "data_source": "shopify_live" if self._shopify.is_connected else "mock",
            "results": results,
            "action_plan": self._generate_action_plan(results),
        }

    def optimize_pricing(self) -> dict[str, Any]:
        """Fetch products → analyze pricing → generate recommendations → plan actions."""
        flow_id = generate_id("flow")
        start = time.monotonic()

        products = self._shopify.fetch_products()

        from engines.registry import get_engine
        from engines.base.engine_types import EngineInput

        # Run pricing engine with full intelligence
        e = get_engine("pricing")
        out = e.run(EngineInput(task_id=f"{flow_id}_pricing", engine_name="pricing",
                                 data={"products": products}))

        # Plan actions from results
        actions = self._execution.plan_actions("pricing", out.result)

        elapsed = time.monotonic() - start

        return {
            "flow_id": flow_id,
            "flow": "optimize_pricing",
            "elapsed_seconds": round(elapsed, 3),
            "products_analyzed": len(products),
            "pricing": {
                "analysis": out.result.get("price_analysis", {}),
                "margins": out.result.get("margin_analysis", {}),
                "recommendations": out.result.get("pricing_recommendations", []),
                "opportunities": out.result.get("pricing_opportunities", []),
            },
            "actions": actions,
        }

    def recover_abandoned_carts(self) -> dict[str, Any]:
        """Analyze abandoned carts → generate recovery emails → plan campaigns."""
        flow_id = generate_id("flow")
        start = time.monotonic()

        from core.intelligence.email_intelligence import EmailIntelligence
        ei = EmailIntelligence()

        # Build recovery flow
        flow = ei.build_automation_flow("abandoned_cart")

        # Score subject lines
        scored_subjects = []
        for email in flow.get("emails", []):
            subject = email.get("subject", "")
            if subject:
                score = ei.score_subject_line(subject)
                scored_subjects.append({
                    "delay": email.get("delay"),
                    "subject": subject,
                    "score": score["score"],
                    "grade": score["grade"],
                })

        elapsed = time.monotonic() - start

        return {
            "flow_id": flow_id,
            "flow": "recover_abandoned_carts",
            "elapsed_seconds": round(elapsed, 3),
            "recovery_flow": flow,
            "subject_scores": scored_subjects,
            "estimated_recovery": flow.get("estimated_recovery", "5-15%"),
        }

    def full_seo_audit(self) -> dict[str, Any]:
        """Fetch products → audit SEO → keyword analysis → action plan."""
        flow_id = generate_id("flow")
        start = time.monotonic()

        products = self._shopify.fetch_products()
        from core.intelligence.seo_intelligence import SEOIntelligence
        si = SEOIntelligence()

        # Audit each product as a page
        audits = []
        for p in products[:10]:
            # W962-75: p.get("name", "") returns None when the
            # key exists with explicit None value; (.lower) on
            # None raises AttributeError. Coerce via `or ""`.
            name = p.get("name", "") or ""
            page = {
                "title": name,
                "url": f"/products/{name.lower().replace(' ', '-')}",
                "keyword": p.get("category", "product") or "product",
            }
            audit = si.audit_page(page)
            audits.append({
                "product": p.get("name"),
                "score": audit["score"],
                "grade": audit["grade"],
                "issues": audit["issue_count"],
                "top_issue": audit["issues"][0]["issue"] if audit["issues"] else "none",
            })

        avg_score = sum(a["score"] for a in audits) / len(audits) if audits else 0

        elapsed = time.monotonic() - start

        return {
            "flow_id": flow_id,
            "flow": "full_seo_audit",
            "elapsed_seconds": round(elapsed, 3),
            "products_audited": len(audits),
            "avg_seo_score": round(avg_score, 1),
            "audits": audits,
            "priority_fixes": sorted(audits, key=lambda a: a["score"])[:3],
        }

    def customer_retention_campaign(self) -> dict[str, Any]:
        """Segment customers → find churn risks → build retention campaign."""
        flow_id = generate_id("flow")
        start = time.monotonic()

        customers = self._shopify.fetch_customers()

        from engines.registry import get_engine
        from engines.base.engine_types import EngineInput
        from core.intelligence.email_intelligence import EmailIntelligence

        # Segment customers
        e = get_engine("customer_segmentation")
        out = e.run(EngineInput(task_id=f"{flow_id}_seg", engine_name="customer_segmentation",
                                 data={"customer_data": customers, "segmentation_criteria": {}}))

        # Build win-back flow for churning customers
        ei = EmailIntelligence()
        win_back = ei.build_automation_flow("win_back", {"inactive_days": 90})
        vip_flow = ei.build_automation_flow("vip")

        # Score win-back subjects
        wb_scores = []
        for email in win_back.get("emails", []):
            s = ei.score_subject_line(email.get("subject", ""))
            wb_scores.append({"subject": email["subject"], "score": s["score"], "grade": s["grade"]})

        elapsed = time.monotonic() - start

        churn_risks = out.result.get("churn_risks", [])
        segments = out.result.get("rfm_segments", {})

        return {
            "flow_id": flow_id,
            "flow": "customer_retention_campaign",
            "elapsed_seconds": round(elapsed, 3),
            "total_customers": len(customers),
            "segments": {seg: info.get("count", 0) for seg, info in segments.items()},
            "at_risk_count": len(churn_risks),
            "churn_risks": churn_risks[:5],
            "win_back_flow": win_back,
            "win_back_subject_scores": wb_scores,
            "vip_flow": vip_flow,
        }

    def _generate_action_plan(self, results: dict) -> list[dict[str, Any]]:
        """Generate prioritized action plan from store analysis."""
        actions = []

        # Product actions
        products = results.get("product_analysis", {})
        if products.get("selected", 0) > 0:
            actions.append({
                "priority": 1,
                "category": "product",
                "action": f"Focus on top product: {products.get('top_product')}",
                "impact": "high",
            })

        # Pricing actions
        pricing = results.get("pricing_analysis", {})
        opps = pricing.get("opportunities", [])
        if opps:
            actions.append({
                "priority": 2,
                "category": "pricing",
                "action": f"{len(opps)} pricing opportunities found — review and implement",
                "impact": "high",
            })

        # Customer actions
        customers = results.get("customer_analysis", {})
        risks = customers.get("churn_risks", [])
        if risks:
            actions.append({
                "priority": 1,
                "category": "customer",
                "action": f"{len(risks)} customers at churn risk — launch win-back campaign",
                "impact": "critical",
            })

        hv = customers.get("high_value", [])
        if hv:
            actions.append({
                "priority": 3,
                "category": "customer",
                "action": f"{len(hv)} high-value customers — launch VIP program",
                "impact": "medium",
            })

        # Revenue actions
        orders = results.get("order_analysis", {})
        aov = orders.get("avg_order_value", 0)
        if aov > 0 and aov < 50:
            actions.append({
                "priority": 2,
                "category": "revenue",
                "action": f"AOV is ${aov:.2f} — implement upsell/cross-sell to increase",
                "impact": "high",
            })

        actions.sort(key=lambda a: a["priority"])
        return actions
