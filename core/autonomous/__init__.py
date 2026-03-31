"""AutonomousOperator — fully autonomous Shopify store operator.

ONE COMMAND runs everything:
  1. Fetch store data (products, customers, orders)
  2. Run unified intelligence (15 modules)
  3. Process automation loop for each event type
  4. Generate actions with priorities
  5. Create reports
  6. Monitor alerts
  7. Track revenue
  8. Learn from outcomes

This is the FINAL layer — everything below it works together.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("autonomous")


class AutonomousOperator:
    """One-button autonomous Shopify store operator."""

    def __init__(self) -> None:
        self._orch = None
        self._cycle_count = 0
        self._total_actions = 0

    def operate(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run ONE full autonomous cycle — analyze everything, decide, plan actions."""
        cycle_id = generate_id("auto")
        start = time.monotonic()
        self._ensure_orch()

        cfg = config or {}
        results = {}

        # 1. FETCH — get all store data
        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge(cfg.get("shop_url", ""), cfg.get("api_key", ""))
        products = sb.fetch_products()
        customers = sb.fetch_customers()
        orders = sb.fetch_orders()
        results["data"] = {"products": len(products), "customers": len(customers), "orders": len(orders)}

        # 2. INTELLIGENCE — run all 15 modules
        from core.intelligence.unified import UnifiedIntelligence
        intel = UnifiedIntelligence().full_store_analysis(
            products=products, customers=customers, orders=orders,
            competitors=cfg.get("competitors", []),
            suppliers=cfg.get("suppliers", []),
            ad_campaigns=cfg.get("ad_campaigns", []),
            funnel_data=cfg.get("funnel_data"),
            traffic_sources=cfg.get("traffic_sources"),
            sessions=cfg.get("sessions"),
        )
        results["intelligence"] = {
            "modules_run": intel["modules_run"],
            "store_score": intel["store_score"],
            "recommendations": len(intel["recommendations"]),
        }

        # 3. AUTOMATION — process events
        from core.automation import AutomationLoop
        al = AutomationLoop()

        auto_results = []
        # Process each product
        for p in products[:3]:
            r = al.process_product_change(p)
            auto_results.append({"type": "product", "name": p.get("name"), "actions": r["action_count"]})

        # Process customer activity
        for c in customers[:3]:
            r = al.process_customer_activity(c)
            auto_results.append({"type": "customer", "name": c.get("name"), "actions": r["action_count"]})

        # Process recent order
        if orders:
            r = al.process_order(orders[0])
            auto_results.append({"type": "order", "actions": r["action_count"]})

        total_auto_actions = sum(a["actions"] for a in auto_results)
        results["automation"] = {"events_processed": len(auto_results), "actions_generated": total_auto_actions}

        # 4. ALERTS — check for problems
        from core.alerts import AlertSystem
        alert_sys = AlertSystem()
        alert_sys.setup_ecommerce_defaults()

        alert_metrics = {
            "stockout_products": sum(1 for p in products if int(p.get("inventory_quantity", 0)) == 0),
            "avg_seo_score": intel["results"].get("seo", {}).get("avg_score", 50),
        }
        if intel["results"].get("ads"):
            for ad in intel["results"]["ads"]:
                alert_metrics["roas"] = ad.get("roas", 0)

        alerts_fired = alert_sys.check(alert_metrics)
        results["alerts"] = {"fired": len(alerts_fired),
                              "critical": sum(1 for a in alerts_fired if a["severity"] == "critical"),
                              "details": [{"severity": a["severity"], "message": a["message"]} for a in alerts_fired]}

        # 5. REPORT — generate daily summary
        from core.reports import ReportGenerator
        report = ReportGenerator().daily_report()
        results["report"] = report.get("summary", {})

        # 6. CHANNEL SYNC — prepare multi-channel feeds
        from core.intelligence.multichannel import MultiChannel
        mc = MultiChannel()
        channel_health = mc.channel_health(products)
        results["channels"] = {ch: {"ready_pct": data["ready_pct"]} for ch, data in channel_health.items()}

        # 7. CONTENT — generate for top product
        if products:
            from core.intelligence.content_generator import ContentGenerator
            cg = ContentGenerator()
            top_product = products[0]
            desc = cg.product_description(top_product)
            results["content"] = {
                "generated_for": top_product.get("name"),
                "headline": desc["headline"][:60],
                "has_bullets": len(desc["bullet_points"]) > 0,
            }

        # 8. FULL SYSTEM LOOP — intelligence + agents + execution + learning (closed loop)
        from core.full_system_loop import FullSystemLoop
        fsl_result = FullSystemLoop().run(
            {"products": products, "customers": customers, "orders": orders},
            config={"goal": cfg.get("goal", "maximize_profit")},
        )
        results["full_loop"] = {
            "status": fsl_result.get("status"),
            "decision": fsl_result.get("phases", {}).get("intelligence", {}).get("decision", {}),
            "confidence_score": fsl_result.get("phases", {}).get("intelligence", {}).get("confidence_score", 0),
            "actions_dispatched": fsl_result.get("phases", {}).get("execution", {}).get("actions_dispatched", 0),
            "outcome_recorded": fsl_result.get("phases", {}).get("learning", {}).get("outcome_recorded", False),
        }

        # 9. SYSTEM HEALTH — self-monitoring
        from core.intelligence.system_health import SystemHealthReport
        health_report = SystemHealthReport().generate()
        results["system_health"] = {
            "grade": health_report.get("overall_grade", "N/A"),
            "sections": {k: v.get("grade", "N/A") for k, v in health_report.get("sections", {}).items()},
        }

        elapsed = time.monotonic() - start
        self._cycle_count += 1
        self._total_actions += total_auto_actions

        # Compile final output
        all_actions = intel.get("top_3_actions", [])

        return {
            "cycle_id": cycle_id,
            "cycle_number": self._cycle_count,
            "elapsed_seconds": round(elapsed, 3),
            "status": "completed",
            "results": results,
            "top_actions": all_actions,
            "store_score": intel["store_score"],
            "summary": self._generate_summary(results, intel, alerts_fired, elapsed),
        }

    def quick_check(self) -> dict[str, Any]:
        """30-second quick health check."""
        start = time.monotonic()
        self._ensure_orch()

        health = self._orch.health_check()
        from core.bridge.shopify_bridge import ShopifyBridge
        products = ShopifyBridge().fetch_products()

        result = self._orch.submit_task("pricing", {"products": products})
        pricing_ok = result.get("status") == "completed"

        return {
            "health": health.get("status"),
            "products": len(products),
            "pricing_ok": pricing_ok,
            "elapsed": round(time.monotonic() - start, 3),
        }

    def _ensure_orch(self) -> None:
        if self._orch is None:
            from core.orchestrator import MainOrchestrator
            self._orch = MainOrchestrator()
            self._orch.initialize()

    @staticmethod
    def _generate_summary(results: dict, intel: dict, alerts: list, elapsed: float) -> str:
        """Human-readable summary of the autonomous cycle."""
        score = intel["store_score"]
        lines = [
            f"Store Score: {score['score']}/100 ({score['grade']})",
            f"Data: {results['data']['products']} products, {results['data']['customers']} customers, {results['data']['orders']} orders",
            f"Intelligence: {results['intelligence']['modules_run']} modules, {results['intelligence']['recommendations']} recommendations",
            f"Automation: {results['automation']['events_processed']} events → {results['automation']['actions_generated']} actions",
        ]
        if results["alerts"]["critical"] > 0:
            lines.append(f"⚠️ {results['alerts']['critical']} CRITICAL alerts!")
        if results["alerts"]["fired"] > 0:
            lines.append(f"Alerts: {results['alerts']['fired']} fired")

        top = intel.get("top_3_actions", [])
        if top:
            lines.append("Top Actions:")
            for a in top[:3]:
                lines.append(f"  → [{a['category']}] {a['action']}")

        lines.append(f"Completed in {elapsed:.3f}s")
        return "\n".join(lines)
