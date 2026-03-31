"""AutoPilot — automated daily store operations.

Runs on schedule:
  - Morning: pricing check, inventory alerts, SEO audit
  - Afternoon: customer segment update, churn detection
  - Evening: daily report generation, forecast update
"""
from __future__ import annotations

import time
import threading
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("autopilot")


class AutoPilot:
    """Automated daily store operations."""

    def __init__(self) -> None:
        self._running = False
        self._thread = None
        self._log: list[dict[str, Any]] = []
        self._orch = None

    def run_daily_cycle(self) -> dict[str, Any]:
        """Run complete daily operations cycle."""
        cycle_id = generate_id("cycle")
        start = time.monotonic()
        results = {}

        self._ensure_orch()

        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge()
        products = sb.fetch_products()
        customers = sb.fetch_customers()
        orders = sb.fetch_orders()

        # 1. Pricing check
        r = self._safe_run("pricing", {"products": products})
        results["pricing"] = {
            "status": r.get("status"),
            "opportunities": len(r.get("result", {}).get("pricing_opportunities", [])),
        }

        # 2. Inventory alerts
        inventory = [{"name": p["name"], "stock": p.get("inventory_quantity", 0),
                       "daily_sales": 3, "lead_time": 7} for p in products]
        r = self._safe_run("inventory", {"inventory_data": inventory})
        stockout = r.get("result", {}).get("stockout_risks", [])
        results["inventory"] = {"status": r.get("status"), "stockout_risks": len(stockout)}

        # 3. SEO audit
        from core.intelligence import SEOIntelligence
        si = SEOIntelligence()
        seo_scores = []
        for p in products[:5]:
            audit = si.audit_page({"title": p["name"], "keyword": p.get("category", "product")})
            seo_scores.append(audit["score"])
        results["seo"] = {"avg_score": round(sum(seo_scores) / max(len(seo_scores), 1), 1), "audited": len(seo_scores)}

        # 4. Customer segments
        r = self._safe_run("customer_segmentation", {"customer_data": customers, "segmentation_criteria": {}})
        churn = r.get("result", {}).get("churn_risks", [])
        results["customers"] = {"status": r.get("status"), "churn_risks": len(churn)}

        # 5. Forecast
        from core.intelligence import Forecasting
        revenue = [float(o.get("total", 0)) for o in orders]
        if len(revenue) >= 3:
            fc = Forecasting().forecast(revenue, periods=7)
            results["forecast"] = {"method": fc.get("method"), "trend": fc.get("trend", {}).get("direction")}
        else:
            results["forecast"] = {"status": "insufficient_data"}

        # 6. Report
        from core.reports import ReportGenerator
        report = ReportGenerator().daily_report()
        results["report"] = report.get("summary", {})

        elapsed = time.monotonic() - start
        cycle = {
            "cycle_id": cycle_id,
            "elapsed_seconds": round(elapsed, 3),
            "timestamp": time.time(),
            "results": results,
            "alerts": self._generate_alerts(results),
        }

        self._log.append(cycle)
        if len(self._log) > 100:
            self._log = self._log[-100:]

        return cycle

    def run_quick_check(self) -> dict[str, Any]:
        """Quick 5-second health + pricing check."""
        self._ensure_orch()
        start = time.monotonic()

        health = self._orch.health_check()
        from core.bridge.shopify_bridge import ShopifyBridge
        products = ShopifyBridge().fetch_products()
        r = self._safe_run("pricing", {"products": products})

        return {
            "health": health.get("status"),
            "products": len(products),
            "pricing_opportunities": len(r.get("result", {}).get("pricing_opportunities", [])),
            "elapsed": round(time.monotonic() - start, 3),
        }

    def start_scheduled(self, interval_hours: int = 24) -> None:
        """Start auto-pilot on schedule."""
        if self._running:
            return
        self._running = True
        interval = interval_hours * 3600

        def loop():
            while self._running:
                try:
                    logger.info("AutoPilot: starting daily cycle")
                    self.run_daily_cycle()
                except Exception as exc:
                    logger.error("AutoPilot cycle failed: %s", exc)
                time.sleep(interval)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        logger.info("AutoPilot started (every %dh)", interval_hours)

    def stop(self) -> None:
        self._running = False

    def get_log(self, limit: int = 10) -> list[dict[str, Any]]:
        return list(self._log[-limit:])

    def _ensure_orch(self) -> None:
        if self._orch is None:
            from core.orchestrator import MainOrchestrator
            self._orch = MainOrchestrator()
            self._orch.initialize()

    def _safe_run(self, engine: str, data: dict) -> dict:
        try:
            return self._orch.submit_task(engine, data)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "result": {}}

    @staticmethod
    def _generate_alerts(results: dict) -> list[dict[str, Any]]:
        alerts = []
        if results.get("inventory", {}).get("stockout_risks", 0) > 0:
            alerts.append({"level": "high", "message": f"{results['inventory']['stockout_risks']} products at stockout risk"})
        if results.get("customers", {}).get("churn_risks", 0) > 0:
            alerts.append({"level": "medium", "message": f"{results['customers']['churn_risks']} customers at churn risk"})
        seo = results.get("seo", {}).get("avg_score", 100)
        if seo < 50:
            alerts.append({"level": "medium", "message": f"SEO avg score {seo}/100 — needs improvement"})
        pricing = results.get("pricing", {}).get("opportunities", 0)
        if pricing > 0:
            alerts.append({"level": "low", "message": f"{pricing} pricing opportunities found"})
        return alerts
