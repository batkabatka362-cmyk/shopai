"""AdsIntelligence — real ad campaign optimization algorithms.

Covers:
  - Campaign performance analysis (CTR, CPC, CPA, ROAS)
  - Budget optimization across channels
  - Ad creative scoring
  - Audience analysis and targeting recommendations
  - Bid strategy optimization
  - Campaign scaling recommendations
"""
from __future__ import annotations

import math
from typing import Any


class AdsIntelligence:
    """Real advertising optimization algorithms."""

    def analyze_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        """Full campaign performance analysis."""
        spend = float(campaign.get("spend", campaign.get("cost", 0)))
        revenue = float(campaign.get("revenue", 0))
        impressions = int(campaign.get("impressions", 0))
        clicks = int(campaign.get("clicks", 0))
        conversions = int(campaign.get("conversions", campaign.get("purchases", 0)))
        aov = float(campaign.get("aov", revenue / max(conversions, 1) if conversions else 0))

        metrics = {"spend": round(spend, 2)}

        if impressions > 0:
            metrics["ctr"] = round(clicks / impressions * 100, 2)
            metrics["cpm"] = round(spend / impressions * 1000, 2)
        if clicks > 0:
            metrics["cpc"] = round(spend / clicks, 2)
            metrics["conversion_rate"] = round(conversions / clicks * 100, 2)
        if conversions > 0:
            metrics["cpa"] = round(spend / conversions, 2)
            metrics["aov"] = round(aov, 2)
        if spend > 0:
            metrics["roas"] = round(revenue / spend, 2)
            metrics["profit"] = round(revenue - spend, 2)
            metrics["roi"] = round((revenue - spend) / spend * 100, 1)

        # Health assessment
        roas = metrics.get("roas", 0)
        ctr = metrics.get("ctr", 0)
        health = self._assess_health(roas, ctr, metrics.get("cpa", 0), aov)

        # Recommendations
        recommendations = self._generate_recommendations(metrics, health)

        return {
            "metrics": metrics,
            "health": health,
            "recommendations": recommendations,
            "scaling": self._scaling_advice(metrics),
        }

    def optimize_budget(self, channels: list[dict[str, Any]], total_budget: float) -> dict[str, Any]:
        """Optimize budget allocation across ad channels."""
        if not channels:
            return {"error": "No channel data"}

        # Calculate efficiency score per channel
        scored = []
        for ch in channels:
            name = ch.get("name", ch.get("channel", "unknown"))
            spend = float(ch.get("spend", 0))
            revenue = float(ch.get("revenue", 0))
            conversions = int(ch.get("conversions", 0))
            clicks = int(ch.get("clicks", 0))

            roas = revenue / max(spend, 1) if spend > 0 else 0
            cpa = spend / max(conversions, 1) if conversions > 0 else spend
            ctr = clicks / max(int(ch.get("impressions", 1)), 1) * 100

            # Efficiency = ROAS weighted by conversion volume
            efficiency = roas * math.log1p(conversions + 1) if roas > 0 else 0

            scored.append({
                "channel": name,
                "current_spend": round(spend, 2),
                "roas": round(roas, 2),
                "cpa": round(cpa, 2),
                "ctr": round(ctr, 2),
                "efficiency": round(efficiency, 2),
                "conversions": conversions,
            })

        # Allocate budget by efficiency
        total_efficiency = sum(s["efficiency"] for s in scored)
        if total_efficiency <= 0:
            # Equal split if no performance data
            equal = round(total_budget / max(len(scored), 1), 2)
            for s in scored:
                s["recommended_budget"] = equal
                s["change"] = round(equal - s["current_spend"], 2)
        else:
            for s in scored:
                share = s["efficiency"] / total_efficiency
                recommended = round(total_budget * share, 2)
                # Cap: no channel gets less than 10% or more than 50%
                recommended = max(total_budget * 0.10, min(total_budget * 0.50, recommended))
                s["recommended_budget"] = recommended
                s["change"] = round(recommended - s["current_spend"], 2)
                s["change_pct"] = round((recommended - s["current_spend"]) / max(s["current_spend"], 1) * 100, 1)

        # Normalize to total budget
        total_recommended = sum(s["recommended_budget"] for s in scored)
        if total_recommended > 0:
            scale = total_budget / total_recommended
            for s in scored:
                s["recommended_budget"] = round(s["recommended_budget"] * scale, 2)
                s["change"] = round(s["recommended_budget"] - s["current_spend"], 2)

        scored.sort(key=lambda s: -s["efficiency"])

        return {
            "total_budget": total_budget,
            "channels": scored,
            "top_channel": scored[0]["channel"] if scored else None,
            "action": f"Shift budget to {scored[0]['channel']}" if scored and scored[0]["efficiency"] > 0 else "Gather more data",
        }

    def score_ad_creative(self, creative: dict[str, Any]) -> dict[str, Any]:
        """Score an ad creative for effectiveness."""
        headline = creative.get("headline", "")
        body = creative.get("body", creative.get("description", ""))
        cta = creative.get("cta", "")
        image = creative.get("has_image", creative.get("image", False))
        platform = creative.get("platform", "facebook")

        score = 50
        factors = []

        # Headline
        if headline:
            hl = len(headline)
            if 20 <= hl <= 40:
                score += 10
                factors.append({"factor": "headline_length", "impact": "+10", "detail": f"{hl} chars — optimal"})
            elif hl > 60:
                score -= 5
                factors.append({"factor": "headline_length", "impact": "-5", "detail": f"{hl} chars — too long"})

            # Power words
            power = ["free", "new", "save", "exclusive", "limited", "now", "today", "sale", "off"]
            hits = [w for w in power if w in headline.lower()]
            if hits:
                score += len(hits) * 5
                factors.append({"factor": "power_words", "impact": f"+{len(hits)*5}", "detail": f"Contains: {hits}"})

            # Numbers
            if any(c.isdigit() for c in headline):
                score += 5
                factors.append({"factor": "number", "impact": "+5", "detail": "Contains number — specific and credible"})

        # Body
        if body:
            bl = len(body)
            platform_limits = {"facebook": 125, "google": 90, "instagram": 2200, "tiktok": 100}
            limit = platform_limits.get(platform, 125)
            if bl <= limit:
                score += 5
                factors.append({"factor": "body_length", "impact": "+5", "detail": f"{bl}/{limit} chars — within limit"})
            else:
                score -= 5
                factors.append({"factor": "body_length", "impact": "-5", "detail": f"{bl}/{limit} chars — over limit"})

            # Benefit-focused
            benefits = ["save", "get", "discover", "enjoy", "transform", "boost", "improve"]
            if any(b in body.lower() for b in benefits):
                score += 5
                factors.append({"factor": "benefit_focus", "impact": "+5"})

        # CTA
        if cta:
            score += 5
            strong_ctas = ["shop now", "buy now", "get started", "learn more", "claim", "try free"]
            if any(c in cta.lower() for c in strong_ctas):
                score += 5
                factors.append({"factor": "strong_cta", "impact": "+5", "detail": f'"{cta}" — clear action'})

        # Image
        if image:
            score += 10
            factors.append({"factor": "has_image", "impact": "+10", "detail": "Visual content boosts engagement"})

        score = max(0, min(100, score))

        return {
            "score": score,
            "grade": "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D",
            "platform": platform,
            "factors": factors,
            "predicted_ctr": self._predict_ctr(score, platform),
            "improvements": self._creative_improvements(headline, body, cta, image, factors),
        }

    def recommend_targeting(self, product: dict[str, Any], customers: list[dict] | None = None) -> dict[str, Any]:
        """Recommend audience targeting for a product."""
        price = float(product.get("price", 0))
        category = product.get("category", "").lower()

        # Demographic targeting
        if price > 100:
            income = "high"
            age_range = "25-54"
        elif price > 30:
            income = "medium"
            age_range = "18-44"
        else:
            income = "broad"
            age_range = "18-34"

        # Interest targeting
        interest_map = {
            "electronics": ["technology", "gadgets", "smartphones", "online shopping"],
            "fitness": ["fitness", "health", "yoga", "exercise", "wellness"],
            "beauty": ["beauty", "skincare", "cosmetics", "self care"],
            "home": ["home decor", "interior design", "home improvement"],
            "fashion": ["fashion", "style", "clothing", "accessories"],
            "food": ["cooking", "food delivery", "healthy eating"],
        }
        interests = interest_map.get(category, ["online shopping", "deals"])

        # Lookalike from customers
        lookalike = None
        if customers:
            top_customers = sorted(customers, key=lambda c: float(c.get("total_spent", 0)), reverse=True)[:100]
            if top_customers:
                lookalike = {
                    "source": "top_customers",
                    "size": len(top_customers),
                    "avg_ltv": round(sum(float(c.get("total_spent", 0)) for c in top_customers) / len(top_customers), 2),
                    "expansion": "1-3%",
                }

        return {
            "demographic": {"age": age_range, "income": income},
            "interests": interests,
            "behaviors": ["online shoppers", "engaged shoppers", f"{category} enthusiasts"],
            "lookalike": lookalike,
            "retargeting": {
                "website_visitors": "30 days",
                "cart_abandoners": "7 days",
                "past_customers": "180 days",
            },
            "budget_recommendation": {
                "testing": round(price * 3, 2),  # 3x product price for initial test
                "scaling": round(price * 10, 2),  # 10x for scaling
            },
        }

    def _assess_health(self, roas: float, ctr: float, cpa: float, aov: float) -> dict[str, Any]:
        issues = []
        if roas < 1:
            issues.append({"metric": "roas", "issue": f"ROAS {roas:.1f}x — losing money", "severity": "critical"})
        elif roas < 2:
            issues.append({"metric": "roas", "issue": f"ROAS {roas:.1f}x — barely profitable", "severity": "warning"})

        if ctr < 1.0:
            issues.append({"metric": "ctr", "issue": f"CTR {ctr:.2f}% — below average", "severity": "warning"})

        if cpa > 0 and aov > 0 and cpa > aov * 0.5:
            issues.append({"metric": "cpa", "issue": f"CPA ${cpa:.2f} is {cpa/aov*100:.0f}% of AOV — too high", "severity": "warning"})

        status = "healthy" if not issues else "critical" if any(i["severity"] == "critical" for i in issues) else "warning"
        return {"status": status, "issues": issues}

    def _generate_recommendations(self, metrics: dict, health: dict) -> list[dict[str, str]]:
        recs = []
        roas = metrics.get("roas", 0)
        ctr = metrics.get("ctr", 0)
        cpa = metrics.get("cpa", 0)

        if roas < 2:
            recs.append({"priority": "high", "action": "Improve ROAS — test new audiences, optimize landing page, or increase AOV"})
        if ctr < 1.5:
            recs.append({"priority": "high", "action": "Improve CTR — test new headlines, images, and ad formats"})
        if cpa > 0 and metrics.get("aov", 0) > 0 and cpa > metrics["aov"] * 0.3:
            recs.append({"priority": "medium", "action": f"Reduce CPA from ${cpa:.2f} — refine targeting or increase bid efficiency"})
        if roas > 3:
            recs.append({"priority": "medium", "action": f"ROAS {roas:.1f}x is strong — consider scaling budget 20-30%"})

        if not recs:
            recs.append({"priority": "low", "action": "Campaign performing well — continue monitoring"})
        return recs

    def _scaling_advice(self, metrics: dict) -> dict[str, Any]:
        roas = metrics.get("roas", 0)
        spend = metrics.get("spend", 0)

        if roas >= 3:
            return {"action": "scale", "increase_pct": 20, "reason": f"ROAS {roas:.1f}x supports scaling",
                    "new_budget": round(spend * 1.2, 2)}
        if roas >= 2:
            return {"action": "maintain", "reason": f"ROAS {roas:.1f}x — maintain and optimize before scaling"}
        if roas >= 1:
            return {"action": "optimize", "reason": f"ROAS {roas:.1f}x — fix targeting/creative before spending more"}
        return {"action": "pause", "reason": f"ROAS {roas:.1f}x — losing money, pause and restructure"}

    @staticmethod
    def _predict_ctr(score: int, platform: str) -> str:
        base = {"facebook": 1.5, "google": 3.0, "instagram": 1.0, "tiktok": 1.5}.get(platform, 1.5)
        predicted = base * (score / 60)
        return f"{predicted:.1f}% (platform avg: {base}%)"

    @staticmethod
    def _creative_improvements(headline, body, cta, image, factors) -> list[str]:
        improvements = []
        if not headline or len(headline) < 10:
            improvements.append("Add a compelling headline with a benefit or number")
        if not cta:
            improvements.append("Add a clear CTA: 'Shop Now', 'Get 20% Off', 'Learn More'")
        if not image:
            improvements.append("Add an eye-catching product image — visuals increase CTR 2-3x")
        if headline and not any(c.isdigit() for c in headline):
            improvements.append("Add a specific number: '20% off', '3-day sale', '500+ reviews'")
        return improvements[:3]
