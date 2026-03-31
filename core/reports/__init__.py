"""Scheduled Reports — auto-generate business reports."""
from __future__ import annotations

import json
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("reports")


class ReportGenerator:
    """Generates business reports from ShopAI data."""

    def daily_report(self) -> dict[str, Any]:
        """Generate daily store performance report."""
        report_id = generate_id("rpt")
        start = time.monotonic()

        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge()
        products = sb.fetch_products()
        orders = sb.fetch_orders()
        customers = sb.fetch_customers()

        # Revenue
        total_revenue = sum(float(o.get("total", 0)) for o in orders)
        avg_order = total_revenue / len(orders) if orders else 0

        # Products
        top_products = sorted(products, key=lambda p: float(p.get("price", 0)) * int(p.get("inventory_quantity", 0)), reverse=True)[:3]

        # Customers
        new_customers = sum(1 for c in customers if c.get("orders", 0) <= 1)
        repeat = sum(1 for c in customers if c.get("orders", 0) > 1)

        # SEO quick check
        from core.intelligence import SEOIntelligence
        si = SEOIntelligence()
        seo_scores = []
        for p in products[:5]:
            audit = si.audit_page({"title": p.get("name", ""), "keyword": p.get("category", "")})
            seo_scores.append(audit["score"])
        avg_seo = sum(seo_scores) / len(seo_scores) if seo_scores else 0

        elapsed = time.monotonic() - start

        return {
            "report_id": report_id,
            "report_type": "daily",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(elapsed, 3),
            "summary": {
                "revenue": {"total": round(total_revenue, 2), "orders": len(orders), "aov": round(avg_order, 2)},
                "products": {"total": len(products), "top_3": [p.get("name") for p in top_products]},
                "customers": {"total": len(customers), "new": new_customers, "repeat": repeat, "repeat_rate": round(repeat / max(len(customers), 1) * 100, 1)},
                "seo": {"avg_score": round(avg_seo, 1), "products_audited": len(seo_scores)},
            },
            "recommendations": self._daily_recommendations(total_revenue, avg_order, repeat, len(customers), avg_seo),
        }

    def weekly_report(self) -> dict[str, Any]:
        """Generate weekly strategic report."""
        daily = self.daily_report()
        daily["report_type"] = "weekly"

        from core.intelligence import Forecasting
        fc = Forecasting()

        # Revenue forecast
        sample_revenue = [100, 120, 115, 130, 125, 140]
        forecast = fc.revenue_forecast(sample_revenue, days_ahead=7)

        daily["forecast"] = {
            "next_7_days": forecast.get("revenue_summary", {}),
            "trend": forecast.get("trend", {}),
        }

        return daily

    def format_text(self, report: dict[str, Any]) -> str:
        """Format report as readable text."""
        s = report.get("summary", {})
        rev = s.get("revenue", {})
        prod = s.get("products", {})
        cust = s.get("customers", {})
        seo = s.get("seo", {})

        lines = [
            f"{'='*50}",
            f"  SHOPAI {report['report_type'].upper()} REPORT",
            f"  {report.get('generated_at', '')}",
            f"{'='*50}",
            "",
            f"  REVENUE",
            f"    Total: ${rev.get('total', 0):,.2f}",
            f"    Orders: {rev.get('orders', 0)}",
            f"    AOV: ${rev.get('aov', 0):,.2f}",
            "",
            f"  PRODUCTS",
            f"    Total: {prod.get('total', 0)}",
            f"    Top 3: {', '.join(prod.get('top_3', []))}",
            "",
            f"  CUSTOMERS",
            f"    Total: {cust.get('total', 0)}",
            f"    New: {cust.get('new', 0)}",
            f"    Repeat rate: {cust.get('repeat_rate', 0)}%",
            "",
            f"  SEO",
            f"    Avg score: {seo.get('avg_score', 0)}/100",
            "",
            f"  RECOMMENDATIONS",
        ]
        for rec in report.get("recommendations", []):
            lines.append(f"    [{rec.get('priority', '?')}] {rec.get('action', '')}")

        if "forecast" in report:
            fc = report["forecast"]
            lines.extend([
                "",
                f"  FORECAST (next 7 days)",
                f"    Revenue: ${fc.get('next_7_days', {}).get('forecast_total', 0):,.2f}",
                f"    Trend: {fc.get('trend', {}).get('direction', '?')}",
            ])

        lines.append(f"\n{'='*50}")
        return "\n".join(lines)

    def decision_accuracy_report(self) -> dict[str, Any]:
        """Report on ShopAI decision quality — is the system getting smarter?"""
        report_id = generate_id("rpt")
        result = {
            "report_id": report_id,
            "report_type": "decision_accuracy",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Decision KPIs
        try:
            from core.intelligence.kpi_tracker import KPITracker
            kpi = KPITracker()
            decision_kpis = kpi.get_decision_kpis()
            result["decision_quality"] = decision_kpis
        except Exception:
            result["decision_quality"] = {"status": "unavailable"}

        # Learning patterns
        try:
            from core.learning.outcome_tracker import OutcomeTracker
            ot = OutcomeTracker()
            il_patterns = ot.get_winning_patterns("intelligence_loop")
            fsl_patterns = ot.get_winning_patterns("full_system_loop")
            result["learning"] = {
                "intelligence_loop": {
                    "outcomes": il_patterns.get("with_outcomes", 0),
                    "success_rate": il_patterns.get("success_rate", 0),
                    "patterns": len(il_patterns.get("patterns", [])),
                },
                "full_system_loop": {
                    "outcomes": fsl_patterns.get("with_outcomes", 0),
                    "success_rate": fsl_patterns.get("success_rate", 0),
                    "patterns": len(fsl_patterns.get("patterns", [])),
                },
            }
        except Exception:
            result["learning"] = {"status": "unavailable"}

        # Strategy optimizer state
        try:
            from core.intelligence.strategy_optimizer import StrategyOptimizer
            so = StrategyOptimizer()
            result["strategy"] = so.get_strategy_report()
        except Exception:
            result["strategy"] = {"status": "unavailable"}

        # Learned weights
        try:
            from core.intelligence_loop import get_learned_weights
            result["learned_weights"] = get_learned_weights()
        except Exception:
            result["learned_weights"] = {}

        # Campaign health
        try:
            from core.intelligence.campaign_optimizer import CampaignOptimizer
            result["campaign_optimizer"] = {"status": "available"}
        except Exception:
            result["campaign_optimizer"] = {"status": "unavailable"}

        # Revenue impact
        try:
            from core.intelligence.revenue_tracker import RevenueTracker
            rt = RevenueTracker()
            result["revenue_impact"] = rt.get_roi_summary()
        except Exception:
            result["revenue_impact"] = {"status": "unavailable"}

        # System health grade
        try:
            from core.intelligence.system_health import SystemHealthReport
            health = SystemHealthReport().generate()
            result["system_health"] = {
                "grade": health.get("overall_grade", "N/A"),
                "sections": {k: v.get("grade", "N/A") for k, v in health.get("sections", {}).items()},
            }
        except Exception:
            result["system_health"] = {"status": "unavailable"}

        return result

    @staticmethod
    def _daily_recommendations(revenue, aov, repeat, total_customers, seo_score) -> list[dict]:
        recs = []
        if aov < 50:
            recs.append({"priority": "high", "action": f"AOV is ${aov:.2f} — add upsell/bundle offers to increase"})
        if total_customers > 0 and repeat / total_customers < 0.3:
            recs.append({"priority": "high", "action": "Repeat rate below 30% — launch retention campaign"})
        if seo_score < 60:
            recs.append({"priority": "medium", "action": f"SEO avg {seo_score:.0f}/100 — fix product titles and descriptions"})
        if not recs:
            recs.append({"priority": "low", "action": "Store performing well — maintain current strategy"})
        return recs
