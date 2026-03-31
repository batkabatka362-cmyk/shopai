"""UnifiedIntelligence — one command, full store analysis using all 12 modules.

Runs ALL intelligence modules on store data and produces
a single, actionable report with prioritized recommendations.
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("intelligence.unified")


class UnifiedIntelligence:
    """Runs all 12 intelligence modules and produces unified analysis."""

    def full_store_analysis(self, products: list[dict], customers: list[dict] | None = None,
                             orders: list[dict] | None = None, competitors: list[dict] | None = None,
                             suppliers: list[dict] | None = None, ad_campaigns: list[dict] | None = None) -> dict[str, Any]:
        """One command — full store intelligence."""
        report_id = generate_id("unified")
        start = time.monotonic()
        results = {}
        all_recommendations = []

        # 1. Product scoring (7-factor)
        if products:
            from core.step_logic.smart_executor import SmartExecutor
            se = SmartExecutor()
            scored = se._score_products(products)
            top = sorted(scored, key=lambda p: p.get("total_score", 0), reverse=True)
            results["products"] = {
                "total": len(products),
                "top_3": [{"name": p.get("name"), "score": p.get("total_score"), "confidence": p.get("confidence")} for p in top[:3]],
                "avg_score": round(sum(p.get("total_score", 0) for p in scored) / max(len(scored), 1), 2),
                "viable": sum(1 for p in scored if p.get("viable")),
            }
            if top and top[0].get("total_score", 0) > 7:
                all_recommendations.append({"priority": 1, "category": "product", "action": f"Focus on {top[0]['name']} (score {top[0]['total_score']})"})

        # 2. Pricing intelligence
        if products:
            from core.intelligence.pricing_intelligence import PricingIntelligence
            pi = PricingIntelligence()
            if competitors:
                p = products[0]
                comp = pi.competitor_response(float(p.get("price", 0)), float(p.get("cost", 0)), competitors)
                results["pricing"] = {"position": comp.get("position"), "price_index": comp.get("price_index"),
                                       "action": comp.get("recommended_action", "")[:60]}
                if comp.get("position") == "overpriced":
                    all_recommendations.append({"priority": 1, "category": "pricing", "action": comp["recommended_action"]})

        # 3. Customer intelligence
        if customers:
            from core.intelligence.recommendation_intelligence import RecommendationIntelligence
            ri = RecommendationIntelligence()
            results["customers"] = {"total": len(customers)}

            # RFM quick
            repeat = sum(1 for c in customers if int(c.get("orders", 0)) > 1)
            results["customers"]["repeat_rate"] = round(repeat / max(len(customers), 1) * 100, 1)
            if results["customers"]["repeat_rate"] < 30:
                all_recommendations.append({"priority": 2, "category": "customer", "action": f"Repeat rate {results['customers']['repeat_rate']}% — launch retention campaign"})

        # 4. SEO
        if products:
            from core.intelligence.seo_intelligence import SEOIntelligence
            si = SEOIntelligence()
            seo_scores = []
            for p in products[:5]:
                audit = si.audit_page({"title": p.get("name", ""), "keyword": p.get("category", "product")})
                seo_scores.append(audit["score"])
            avg_seo = round(sum(seo_scores) / max(len(seo_scores), 1), 1)
            results["seo"] = {"avg_score": avg_seo, "audited": len(seo_scores)}
            if avg_seo < 60:
                all_recommendations.append({"priority": 2, "category": "seo", "action": f"SEO avg {avg_seo}/100 — fix titles and descriptions"})

        # 5. Email flows
        from core.intelligence.email_intelligence import EmailIntelligence
        ei = EmailIntelligence()
        results["email"] = {
            "flows_available": ["welcome", "abandoned_cart", "post_purchase", "win_back", "browse_abandonment", "vip"],
            "top_priority": "abandoned_cart",
        }
        all_recommendations.append({"priority": 3, "category": "email", "action": "Set up abandoned cart recovery (est. 5-15% recovery)"})

        # 6. Forecasting
        if orders:
            revenue_values = [float(o.get("total", 0)) for o in orders]
            if len(revenue_values) >= 3:
                from core.intelligence.forecasting import Forecasting
                fc = Forecasting().forecast(revenue_values, periods=7)
                results["forecast"] = {"method": fc.get("method"), "trend": fc.get("trend", {}).get("direction"),
                                        "next_7_days": fc.get("forecast", [])}

        # 7. Financial
        if products:
            from core.intelligence.financial_intelligence import FinancialIntelligence
            fi = FinancialIntelligence()
            p = products[0]
            ue = fi.unit_economics(p)
            results["financials"] = {
                "gross_margin": ue["profit"]["gross_margin_pct"],
                "net_margin": ue["profit"]["net_margin_pct"],
            }

        # 8. Dropship scoring
        if products and suppliers:
            from core.intelligence.autods_intelligence import AutoDSIntelligence
            ds = AutoDSIntelligence()
            best = ds.score_product_for_dropship(products[0], suppliers)
            results["dropship"] = {"score": best["score"], "grade": best["grade"],
                                    "net_profit_per_unit": best["financials"]["net_profit"]}

        # 9. Competitor
        if competitors and products:
            from core.intelligence.competitor_intelligence import CompetitorIntelligence
            ci = CompetitorIntelligence()
            comp_result = ci.analyze_competitors({"products": products}, competitors)
            results["competition"] = {
                "position": comp_result["our_position"]["positioning"],
                "threats": len([a for a in comp_result.get("competitors", []) if a.get("threat_level") == "high"]),
                "opportunities": len(comp_result.get("opportunities", [])),
            }
            for opp in comp_result.get("opportunities", [])[:2]:
                all_recommendations.append({"priority": 3, "category": "competition", "action": opp["action"][:60]})

        # 10. Ads
        if ad_campaigns:
            from core.intelligence.ads_intelligence import AdsIntelligence
            ads = AdsIntelligence()
            for camp in ad_campaigns[:3]:
                analysis = ads.analyze_campaign(camp)
                roas = analysis["metrics"].get("roas", 0)
                scaling = analysis["scaling"]["action"]
                results.setdefault("ads", []).append({
                    "name": camp.get("name", "campaign"),
                    "roas": roas,
                    "scaling": scaling,
                })
                if scaling == "pause":
                    all_recommendations.append({"priority": 1, "category": "ads", "action": f"Pause {camp.get('name', 'campaign')} — ROAS {roas}x losing money"})
                elif scaling == "scale":
                    all_recommendations.append({"priority": 2, "category": "ads", "action": f"Scale {camp.get('name', 'campaign')} +20% — ROAS {roas}x"})

        # 11. Content
        if products:
            from core.intelligence.content_generator import ContentGenerator
            cg = ContentGenerator()
            sample = cg.product_description(products[0])
            results["content"] = {"sample_headline": sample["headline"][:60], "ready": True}

        # 12. Visual
        if products:
            from core.intelligence.visual_content_ai import VisualContentAI
            vc = VisualContentAI()
            brief = vc.product_image_brief(products[0])
            results["visual"] = {"shots_needed": len(brief["shots"]), "formats": len(brief["formats"])}

        elapsed = time.monotonic() - start

        # Sort recommendations by priority
        all_recommendations.sort(key=lambda r: r["priority"])

        return {
            "report_id": report_id,
            "elapsed_seconds": round(elapsed, 3),
            "modules_run": len(results),
            "results": results,
            "recommendations": all_recommendations,
            "top_3_actions": all_recommendations[:3],
            "store_score": self._calculate_store_score(results),
        }

    @staticmethod
    def _calculate_store_score(results: dict) -> dict[str, Any]:
        """Overall store health score 0-100."""
        score = 50
        factors = []

        # Product quality
        avg_product = results.get("products", {}).get("avg_score", 0)
        if avg_product > 7:
            score += 15
            factors.append("Strong product lineup")
        elif avg_product > 5:
            score += 5

        # SEO
        seo = results.get("seo", {}).get("avg_score", 0)
        if seo > 70:
            score += 10
            factors.append("Good SEO")
        elif seo < 50:
            score -= 5
            factors.append("SEO needs work")

        # Financial
        margin = results.get("financials", {}).get("gross_margin_pct", 0)
        if margin > 50:
            score += 10
            factors.append("Healthy margins")
        elif margin < 30:
            score -= 5

        # Customer
        repeat = results.get("customers", {}).get("repeat_rate", 0)
        if repeat > 40:
            score += 10
            factors.append("Strong repeat rate")
        elif repeat < 20:
            score -= 5

        score = max(0, min(100, score))
        return {
            "score": score,
            "grade": "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D",
            "factors": factors,
        }
