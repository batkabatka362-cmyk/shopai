"""MarketingLogic — deep business logic for marketing engines.

Uses EmailIntelligence for real email optimization.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from core.intelligence.email_intelligence import EmailIntelligence

_ei = EmailIntelligence()


class MarketingLogic:
    """Real marketing computations."""

    MARKETING_ENGINES = {
        "marketing", "campaign", "email_marketing", "social_media", "ads",
        "attribution", "audience_targeting",
        "influencer", "affiliate", "ab_testing", "landing_page",
        "ad_copy",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.MARKETING_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        campaign = data.get("campaign_data", data.get("campaign", {}))
        audience = data.get("audience_data", data.get("audience_segment", {}))

        if isinstance(campaign, dict) and campaign:
            result["campaign_analysis"] = self._analyze_campaign(campaign)

        if isinstance(audience, (dict, list)):
            result["audience_analysis"] = self._analyze_audience(audience)

        channels = data.get("channel_data", data.get("channels", []))
        if isinstance(channels, list) and channels:
            result["channel_analysis"] = self._analyze_channels(channels)

        result["score"] = self._marketing_score(result)
        result["decision"] = "approve" if result["score"] >= 5 else "reject"
        result["reason"] = self._marketing_reason(result)
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        campaign = data.get("campaign_data", data.get("campaign", {}))
        audience = data.get("audience_data", {})
        # Budget can be top-level or inside campaign_data
        budget = float(data.get("budget", data.get("total_budget", 0)))
        if budget == 0 and isinstance(campaign, dict):
            budget = float(campaign.get("budget", campaign.get("total_budget", 0)))

        if budget > 0:
            result["budget_allocation"] = self._allocate_budget(budget, data)
        else:
            result["budget_allocation"] = {"note": "No budget specified — using default split",
                                           "facebook": 300, "google": 350, "email": 150, "social": 100, "other": 100}

        if isinstance(campaign, dict):
            result["campaign_plan"] = self._build_campaign_plan(campaign, data)

        result["content_calendar"] = self._generate_content_calendar(data)
        result["kpi_targets"] = self._set_kpi_targets(data)

        # Email intelligence
        subject = data.get("subject_line", data.get("subject", ""))
        if isinstance(subject, str) and subject:
            result["subject_score"] = _ei.score_subject_line(subject)

        flow_type = data.get("flow_type", data.get("automation_type", ""))
        if isinstance(flow_type, str) and flow_type:
            result["email_flow"] = _ei.build_automation_flow(flow_type, data)
        elif "email" in str(data.get("_step", "")):
            result["email_flows_available"] = [
                {"type": "welcome", "description": "Welcome series for new customers"},
                {"type": "abandoned_cart", "description": "Recover abandoned checkouts"},
                {"type": "post_purchase", "description": "Post-purchase engagement"},
                {"type": "win_back", "description": "Re-engage inactive customers"},
                {"type": "browse_abandonment", "description": "Follow up on browsed products"},
                {"type": "vip", "description": "VIP customer program"},
            ]

        result["generated"] = True
        return result

    def _analyze_campaign(self, campaign: dict) -> dict:
        spend = float(campaign.get("spend", campaign.get("budget", 0)))
        revenue = float(campaign.get("revenue", 0))
        impressions = int(campaign.get("impressions", 0))
        clicks = int(campaign.get("clicks", 0))
        conversions = int(campaign.get("conversions", 0))

        analysis = {"spend": spend}
        if spend > 0 and revenue > 0:
            analysis["roas"] = round(revenue / spend, 2)
        if impressions > 0:
            analysis["ctr"] = round(clicks / impressions * 100, 4) if clicks else 0
            analysis["cpm"] = round(spend / impressions * 1000, 2) if spend else 0
        if clicks > 0:
            analysis["cpc"] = round(spend / clicks, 2) if spend else 0
            analysis["conversion_rate"] = round(conversions / clicks * 100, 2) if conversions else 0
        if conversions > 0:
            analysis["cpa"] = round(spend / conversions, 2) if spend else 0
            analysis["revenue_per_conversion"] = round(revenue / conversions, 2) if revenue else 0

        # Health assessment
        roas = analysis.get("roas", 0)
        analysis["health"] = "excellent" if roas > 5 else "good" if roas > 3 else "acceptable" if roas > 1.5 else "poor" if roas > 0 else "no_data"

        return analysis

    def _analyze_audience(self, audience: Any) -> dict:
        if isinstance(audience, dict):
            return {"type": "single_segment", "size": audience.get("size", 0), "fields": list(audience.keys())}
        if isinstance(audience, list):
            return {
                "type": "multi_segment",
                "segment_count": len(audience),
                "total_size": sum(a.get("size", 0) for a in audience if isinstance(a, dict)),
            }
        return {"type": "unknown"}

    def _analyze_channels(self, channels: list) -> dict:
        channel_perf = []
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            name = ch.get("name", ch.get("channel", "unknown"))
            spend = float(ch.get("spend", 0))
            revenue = float(ch.get("revenue", 0))
            roas = round(revenue / spend, 2) if spend > 0 else 0
            channel_perf.append({"channel": name, "spend": spend, "revenue": revenue, "roas": roas})

        channel_perf.sort(key=lambda x: x["roas"], reverse=True)
        return {
            "channels": channel_perf,
            "best_channel": channel_perf[0]["channel"] if channel_perf else None,
            "worst_channel": channel_perf[-1]["channel"] if channel_perf else None,
        }

    def _allocate_budget(self, budget: float, data: dict) -> dict:
        channels = data.get("channel_data", data.get("channels", []))
        if not channels:
            return {
                "facebook": round(budget * 0.30, 2),
                "google": round(budget * 0.35, 2),
                "email": round(budget * 0.15, 2),
                "social_organic": round(budget * 0.10, 2),
                "other": round(budget * 0.10, 2),
            }

        # Performance-based allocation
        total_roas = 0
        channel_roas = {}
        for ch in channels:
            if isinstance(ch, dict):
                name = ch.get("name", ch.get("channel", "unknown"))
                spend = float(ch.get("spend", 0))
                revenue = float(ch.get("revenue", 0))
                roas = revenue / spend if spend > 0 else 1
                channel_roas[name] = roas
                total_roas += roas

        if total_roas == 0:
            equal = round(budget / max(len(channel_roas), 1), 2)
            return {name: equal for name in channel_roas}

        return {name: round(budget * (roas / total_roas), 2) for name, roas in channel_roas.items()}

    def _build_campaign_plan(self, campaign: dict, data: dict) -> dict:
        goal = campaign.get("goal", campaign.get("objective", "awareness"))
        return {
            "objective": goal,
            "phases": [
                {"phase": "launch", "duration_days": 7, "focus": "awareness", "budget_pct": 30},
                {"phase": "optimize", "duration_days": 14, "focus": "engagement", "budget_pct": 40},
                {"phase": "scale", "duration_days": 9, "focus": "conversion", "budget_pct": 30},
            ],
            "total_duration_days": 30,
        }

    def _generate_content_calendar(self, data: dict) -> list[dict]:
        return [
            {"week": 1, "content_type": "launch_announcement", "channels": ["email", "social"]},
            {"week": 2, "content_type": "product_spotlight", "channels": ["social", "blog"]},
            {"week": 3, "content_type": "social_proof", "channels": ["social", "email"]},
            {"week": 4, "content_type": "urgency_offer", "channels": ["email", "ads"]},
        ]

    def _set_kpi_targets(self, data: dict) -> dict:
        budget = float(data.get("budget", data.get("total_budget", 1000)))
        return {
            "impressions": int(budget * 100),
            "clicks": int(budget * 5),
            "ctr_target": 2.0,
            "conversions": int(budget * 0.15),
            "conversion_rate_target": 3.0,
            "roas_target": 3.0,
            "cpa_target": round(budget / max(int(budget * 0.15), 1), 2),
        }

    def _marketing_score(self, analysis: dict) -> float:
        score = 5.0
        campaign = analysis.get("campaign_analysis", {})
        roas = campaign.get("roas", 0)
        if roas > 3: score += 2
        elif roas > 1.5: score += 1
        elif roas > 0 and roas < 1: score -= 2
        audience = analysis.get("audience_analysis", {})
        if audience.get("total_size", audience.get("size", 0)) > 1000: score += 1
        return min(round(score, 1), 10)

    def _marketing_reason(self, analysis: dict) -> str:
        campaign = analysis.get("campaign_analysis", {})
        health = campaign.get("health", "no_data")
        roas = campaign.get("roas", 0)
        return f"Campaign health: {health}, ROAS: {roas}"
