"""Marketing Tactics — real-world marketing intelligence from 10 years experience.

What veterans know:
  - Creative fatigue: Ads lose 30-40% effectiveness after 2-3 weeks
  - Audience overlap: Running similar FB ad sets = bidding against yourself
  - Sequential retargeting: Day 1-3 reminder → Day 4-7 social proof → Day 8-14 urgency
  - Micro-influencer ROI: 1K-50K followers deliver 5x better ROI than mega
  - Social proof hierarchy: Photo reviews (4.5x) > text reviews (2.5x) > stars (1.5x)
  - Email segmentation: 760% more revenue than broadcast
  - Referral economics: Referred customers have 25-50% higher LTV
"""
from __future__ import annotations

import math
import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.marketing_tactics")


# Social proof conversion multipliers
SOCIAL_PROOF_MULTIPLIERS = {
    "video_review": 6.0,
    "photo_review": 4.5,
    "text_review": 2.5,
    "star_rating_only": 1.5,
    "no_reviews": 1.0,
}

# Influencer tier economics
INFLUENCER_TIERS = {
    "nano": {"followers": (1000, 10000), "engagement_rate": 0.07, "cost_per_post": (50, 250), "roi_multiplier": 5.0},
    "micro": {"followers": (10000, 50000), "engagement_rate": 0.04, "cost_per_post": (250, 1000), "roi_multiplier": 4.0},
    "mid": {"followers": (50000, 500000), "engagement_rate": 0.02, "cost_per_post": (1000, 5000), "roi_multiplier": 2.0},
    "macro": {"followers": (500000, 1000000), "engagement_rate": 0.015, "cost_per_post": (5000, 15000), "roi_multiplier": 1.2},
    "mega": {"followers": (1000000, float("inf")), "engagement_rate": 0.01, "cost_per_post": (15000, 100000), "roi_multiplier": 0.8},
}

# Retargeting sequence
RETARGETING_SEQUENCE = [
    {"days": (1, 3), "message": "product_reminder", "cta": "Still interested?", "discount": 0},
    {"days": (4, 7), "message": "social_proof", "cta": "See what others say", "discount": 0},
    {"days": (8, 14), "message": "urgency", "cta": "Limited stock", "discount": 0.05},
    {"days": (15, 21), "message": "incentive", "cta": "Special offer for you", "discount": 0.10},
    {"days": (22, 30), "message": "last_chance", "cta": "Final reminder", "discount": 0.15},
]

# Lookalike audience tiers
LOOKALIKE_TIERS = {
    1: {"quality": "highest", "volume": "lowest", "cpa_multiplier": 0.7, "use_case": "Scale proven winning ads"},
    2: {"quality": "high", "volume": "low", "cpa_multiplier": 0.85, "use_case": "Expand successful campaigns"},
    3: {"quality": "medium-high", "volume": "medium", "cpa_multiplier": 1.0, "use_case": "Balanced reach"},
    5: {"quality": "medium", "volume": "high", "cpa_multiplier": 1.3, "use_case": "Broad prospecting"},
    10: {"quality": "low", "volume": "highest", "cpa_multiplier": 1.8, "use_case": "Brand awareness only"},
}


class MarketingTactics:
    """Real-world marketing intelligence engine."""

    def __init__(self, *, llm: Any = None) -> None:
        self._llm = llm

    def full_analysis(
        self,
        campaigns: list[dict[str, Any]] | None = None,
        products: list[dict[str, Any]] | None = None,
        customers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run full marketing tactics analysis."""
        result: dict[str, Any] = {}

        if campaigns:
            result["creative_fatigue"] = self.detect_creative_fatigue(campaigns)
            result["audience_overlap"] = self.detect_audience_overlap(campaigns)
            result["retargeting_plan"] = self.plan_retargeting_sequence(campaigns)
            result["lookalike_strategy"] = self.recommend_lookalike_tiers(campaigns)

        if products:
            result["social_proof_audit"] = self.audit_social_proof(products)
            result["influencer_strategy"] = self.plan_influencer_strategy(products)

        if customers:
            result["referral_opportunity"] = self.analyze_referral_opportunity(customers)
            result["email_segmentation"] = self.recommend_email_segments(customers)

        return result

    def detect_creative_fatigue(self, campaigns: list[dict[str, Any]]) -> dict[str, Any]:
        """Detect ad creative fatigue — ads lose 30-40% effectiveness after 2-3 weeks.

        Signals:
          - CTR declining over time
          - CPA increasing
          - Frequency > 3 (same person seeing ad 3+ times)
        """
        fatigued = []
        healthy = []

        for campaign in campaigns:
            if not isinstance(campaign, dict):
                continue

            name = campaign.get("name", campaign.get("id", "unknown"))
            days_running = safe_int(campaign.get("days_running", 0))
            ctr = safe_float(campaign.get("ctr", 0))
            ctr_7d_ago = safe_float(campaign.get("ctr_7d_ago", ctr))
            frequency = safe_float(campaign.get("frequency", 1))
            cpa = safe_float(campaign.get("cpa", 0))
            cpa_7d_ago = safe_float(campaign.get("cpa_7d_ago", cpa))

            fatigue_signals = 0
            reasons = []

            # CTR declining
            if ctr_7d_ago > 0 and ctr < ctr_7d_ago * 0.8:
                fatigue_signals += 1
                reasons.append(f"CTR dropped {round((1 - ctr/ctr_7d_ago) * 100)}% in 7 days")

            # High frequency
            if frequency > 3:
                fatigue_signals += 1
                reasons.append(f"Frequency {frequency:.1f} — audience seeing ad too often")

            # CPA increasing
            if cpa_7d_ago > 0 and cpa > cpa_7d_ago * 1.3:
                fatigue_signals += 1
                reasons.append(f"CPA increased {round((cpa/cpa_7d_ago - 1) * 100)}%")

            # Running too long without refresh
            if days_running > 21:
                fatigue_signals += 1
                reasons.append(f"Running {days_running} days without creative refresh")

            is_fatigued = fatigue_signals >= 2

            entry = {
                "campaign": name,
                "days_running": days_running,
                "fatigue_signals": fatigue_signals,
                "is_fatigued": is_fatigued,
                "reasons": reasons,
                "action": self._fatigue_action(fatigue_signals, days_running),
            }

            if is_fatigued:
                fatigued.append(entry)
            else:
                healthy.append(entry)

        return {
            "fatigued_campaigns": len(fatigued),
            "healthy_campaigns": len(healthy),
            "details": fatigued + healthy,
            "estimated_waste": f"{len(fatigued) * 35}% budget waste on fatigued creatives" if fatigued else "No waste detected",
        }

    def detect_audience_overlap(self, campaigns: list[dict[str, Any]]) -> dict[str, Any]:
        """Detect audience overlap between ad sets — bidding against yourself wastes 20-40% budget.

        Checks for similar targeting across active campaigns.
        """
        active = [c for c in campaigns if isinstance(c, dict) and c.get("status") == "active"]
        if len(active) < 2:
            return {"status": "insufficient_campaigns", "note": "Need 2+ active campaigns to check overlap"}

        overlaps = []
        for i, camp_a in enumerate(active):
            for camp_b in active[i + 1:]:
                overlap = self._calculate_overlap(camp_a, camp_b)
                if overlap["overlap_pct"] > 30:
                    overlaps.append(overlap)

        return {
            "overlapping_pairs": len(overlaps),
            "details": overlaps,
            "estimated_budget_waste": f"{min(len(overlaps) * 15, 40)}%" if overlaps else "0%",
            "recommendation": (
                f"Consolidate {len(overlaps)} overlapping ad sets to reduce self-competition"
                if overlaps else "No significant audience overlap detected"
            ),
        }

    def plan_retargeting_sequence(self, campaigns: list[dict[str, Any]]) -> dict[str, Any]:
        """Plan a multi-stage retargeting sequence.

        Best practice: escalating message + offer over 30 days.
        """
        return {
            "sequence": RETARGETING_SEQUENCE,
            "total_stages": len(RETARGETING_SEQUENCE),
            "duration_days": 30,
            "expected_recovery_rate": "15-25% of abandoned visitors",
            "key_principle": "Escalate urgency and incentive over time — don't lead with discount",
        }

    def recommend_lookalike_tiers(self, campaigns: list[dict[str, Any]]) -> dict[str, Any]:
        """Recommend lookalike audience sizes based on campaign goals."""
        return {
            "tiers": {
                f"{pct}%": {
                    "quality": info["quality"],
                    "cpa_multiplier": f"{info['cpa_multiplier']}x",
                    "use_case": info["use_case"],
                }
                for pct, info in LOOKALIKE_TIERS.items()
            },
            "recommendation": "Start with 1% lookalike from top 100 customers by LTV. "
                            "Scale to 2-3% only after 1% is profitable.",
        }

    def audit_social_proof(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        """Audit social proof across products — photo reviews convert 4.5x better than no reviews."""
        results = []
        for product in products:
            if not isinstance(product, dict):
                continue

            name = product.get("title", product.get("name", "Unknown"))
            review_count = safe_int(product.get("review_count", product.get("reviews", 0)))
            rating = safe_float(product.get("rating", 0))
            has_photos = product.get("has_photo_reviews", False)
            has_video = product.get("has_video_reviews", False)

            # Determine social proof level
            if has_video and review_count >= 10:
                level = "video_review"
            elif has_photos and review_count >= 5:
                level = "photo_review"
            elif review_count >= 3:
                level = "text_review"
            elif rating > 0:
                level = "star_rating_only"
            else:
                level = "no_reviews"

            multiplier = SOCIAL_PROOF_MULTIPLIERS[level]
            results.append({
                "product": name,
                "review_count": review_count,
                "rating": rating,
                "social_proof_level": level,
                "conversion_multiplier": f"{multiplier}x",
                "improvement_action": self._social_proof_action(level, review_count),
            })

        # Sort by weakest social proof first (most opportunity)
        results.sort(key=lambda r: SOCIAL_PROOF_MULTIPLIERS.get(r["social_proof_level"], 0))

        weak = [r for r in results if r["social_proof_level"] in ("no_reviews", "star_rating_only")]
        return {
            "products_audited": len(results),
            "weak_social_proof": len(weak),
            "details": results,
            "recommendation": (
                f"{len(weak)} products need better social proof. "
                "Priority: get photo reviews on top-selling products."
                if weak else "Social proof is strong across products."
            ),
        }

    def plan_influencer_strategy(self, products: list[dict[str, Any]]) -> dict[str, Any]:
        """Plan influencer marketing strategy — micro-influencers deliver 5x better ROI."""
        avg_price = 0
        if products:
            prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)]
            avg_price = sum(prices) / max(len(prices), 1)

        # Recommend tier based on product price
        if avg_price < 30:
            recommended = "nano"
        elif avg_price < 100:
            recommended = "micro"
        elif avg_price < 500:
            recommended = "mid"
        else:
            recommended = "macro"

        tier = INFLUENCER_TIERS[recommended]
        budget_range = tier["cost_per_post"]

        return {
            "recommended_tier": recommended,
            "tier_details": {
                k: {
                    "followers": f"{v['followers'][0]:,}-{v['followers'][1]:,}" if v["followers"][1] != float("inf") else f"{v['followers'][0]:,}+",
                    "avg_engagement": f"{v['engagement_rate']*100:.1f}%",
                    "cost_per_post": f"${v['cost_per_post'][0]}-${v['cost_per_post'][1]}",
                    "roi_multiplier": f"{v['roi_multiplier']}x",
                }
                for k, v in INFLUENCER_TIERS.items()
            },
            "budget_recommendation": {
                "per_post": f"${budget_range[0]}-${budget_range[1]}",
                "monthly_budget": f"${budget_range[0]*4}-${budget_range[1]*4}",
                "posts_per_month": "4-8 posts across 3-5 influencers",
            },
            "key_insight": "Micro-influencers (10K-50K followers) deliver 5x better ROI than mega-influencers. "
                          "Their audiences trust recommendations more and engagement rates are 4x higher.",
        }

    def analyze_referral_opportunity(self, customers: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze referral program opportunity — referred customers have 25-50% higher LTV."""
        if not customers:
            return {"status": "no_data"}

        total = len(customers)
        order_counts = [safe_int(c.get("orders_count", 0)) for c in customers if isinstance(c, dict)]
        repeat_customers = sum(1 for oc in order_counts if oc > 1)
        avg_orders = sum(order_counts) / max(total, 1)

        # Estimate referral program impact
        repeat_pct = repeat_customers / max(total, 1)
        potential_referrers = int(total * repeat_pct)  # Repeat customers are most likely to refer
        expected_referrals = int(potential_referrers * 0.15)  # 15% of repeat customers refer
        referred_ltv_lift = 0.35  # 35% higher LTV for referred customers

        return {
            "total_customers": total,
            "repeat_customers": repeat_customers,
            "potential_referrers": potential_referrers,
            "expected_monthly_referrals": expected_referrals,
            "referred_customer_ltv_lift": f"+{referred_ltv_lift*100:.0f}%",
            "recommended_incentive": {
                "referrer": "$10 store credit per successful referral",
                "referee": "10% off first order",
            },
            "key_insight": "Referred customers convert 4x higher and have 25-50% higher lifetime value. "
                          "A referral program typically costs 5-10% of acquisition cost.",
        }

    def recommend_email_segments(self, customers: list[dict[str, Any]]) -> dict[str, Any]:
        """Recommend email segments — segmented campaigns drive 760% more revenue than broadcast."""
        segments = {
            "vip": {"criteria": "Top 10% by spend", "frequency": "Weekly exclusive offers", "tone": "Premium, exclusive"},
            "active_buyers": {"criteria": "Purchased in last 30 days", "frequency": "Bi-weekly", "tone": "Helpful, product tips"},
            "at_risk": {"criteria": "No purchase in 60-90 days", "frequency": "Weekly winback", "tone": "We miss you, incentive"},
            "lapsed": {"criteria": "No purchase in 90+ days", "frequency": "Monthly", "tone": "Last chance, big incentive"},
            "new_subscribers": {"criteria": "Email only, no purchase", "frequency": "Welcome series (5 emails)", "tone": "Educational, trust-building"},
            "cart_abandoners": {"criteria": "Added to cart, didn't buy", "frequency": "3-email sequence over 48h", "tone": "Reminder, then urgency"},
            "browse_abandoners": {"criteria": "Viewed product, didn't add to cart", "frequency": "1-2 emails over 7 days", "tone": "Soft reminder, social proof"},
        }

        return {
            "segments": segments,
            "total_segments": len(segments),
            "key_insight": "Segmented email campaigns generate 760% more revenue than one-size-fits-all. "
                          "Start with VIP + at-risk segments for highest immediate impact.",
            "priority_order": ["cart_abandoners", "vip", "at_risk", "new_subscribers", "active_buyers", "lapsed", "browse_abandoners"],
        }

    def _fatigue_action(self, signals: int, days: int) -> str:
        if signals >= 3:
            return "URGENT: Pause and refresh creative immediately"
        if signals >= 2:
            return "Rotate creative within 48 hours"
        if days > 14:
            return "Schedule creative refresh this week"
        return "Healthy — monitor weekly"

    def _social_proof_action(self, level: str, count: int) -> str:
        if level == "no_reviews":
            return "Send post-purchase review request email with photo incentive"
        if level == "star_rating_only":
            return "Offer $5 coupon for photo/video reviews"
        if level == "text_review" and count < 10:
            return "Need more reviews — add review request to unboxing insert card"
        return "Strong — consider featuring in ads"

    def _calculate_overlap(self, camp_a: dict, camp_b: dict) -> dict[str, Any]:
        """Estimate audience overlap between two campaigns."""
        interests_a = set(camp_a.get("interests", []))
        interests_b = set(camp_b.get("interests", []))
        age_a = camp_a.get("age_range", (18, 65))
        age_b = camp_b.get("age_range", (18, 65))

        interest_overlap = len(interests_a & interests_b) / max(len(interests_a | interests_b), 1) * 100 if interests_a or interests_b else 50
        age_overlap = max(0, min(age_a[1], age_b[1]) - max(age_a[0], age_b[0])) / max(age_a[1] - age_a[0], 1) * 100

        overlap_pct = round((interest_overlap + age_overlap) / 2, 1)

        return {
            "campaign_a": camp_a.get("name", camp_a.get("id", "?")),
            "campaign_b": camp_b.get("name", camp_b.get("id", "?")),
            "overlap_pct": overlap_pct,
            "action": "Consolidate or exclude" if overlap_pct > 50 else "Monitor",
        }

    # ── LLM strategy synthesizer ──────────────────────────────

    def synthesize_strategy_with_llm(
        self,
        campaigns: list[dict[str, Any]] | None = None,
        products: list[dict[str, Any]] | None = None,
        customers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run the heuristic full_analysis, then ask the LLM to
        synthesize the findings into a prioritized action plan.

        Returns:
            {
                "heuristic": <full_analysis output>,
                "llm": {priorities, top_action, expected_lift,
                        confidence, reasoning} or {"error": "..."},
                "source": "llm" | "heuristic_only",
            }
        """
        heuristic = self.full_analysis(
            campaigns=campaigns, products=products, customers=customers,
        )
        result: dict[str, Any] = {
            "heuristic": heuristic,
            "llm": None,
            "source": "heuristic_only",
        }

        if not heuristic:
            return result

        llm = self._get_llm()
        if llm is None:
            return result
        try:
            if not llm.is_available():
                return result
        except Exception:  # noqa: BLE001
            return result

        try:
            from core.system.prompt_library import get_prompt
        except Exception:  # noqa: BLE001
            return result
        template = get_prompt("marketing.synthesize_strategy")
        if template is None:
            return result

        # Build a compact JSON summary so the LLM has the full context
        try:
            import json
            summary_json = json.dumps(heuristic, default=str)[:3000]
        except Exception:  # noqa: BLE001
            return result

        rendered = template.render(
            campaign_count=len(campaigns or []),
            product_count=len(products or []),
            customer_count=len(customers or []),
            heuristic_summary=summary_json,
        )

        try:
            structured = llm.ask_structured(
                role=template.role,
                prompt=rendered.user,
                system_prompt=rendered.system,
                schema_hint=template.schema_hint,
            )
        except Exception as exc:  # noqa: BLE001
            result["llm"] = {"error": str(exc)[:200]}
            return result

        if not getattr(structured, "ok", False):
            result["llm"] = {"error": structured.error or "unparseable"}
            return result

        data = structured.data or {}
        try:
            priorities = data.get("priorities") or []
            if not isinstance(priorities, list):
                priorities = []
            result["llm"] = {
                "priorities": [str(p) for p in priorities[:8]],
                "top_action": str(data.get("top_action", "")),
                "expected_lift_pct": float(data.get("expected_lift_pct", 0)),
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                "reasoning": str(data.get("reasoning", ""))[:500],
            }
            result["source"] = "llm"
        except (TypeError, ValueError) as exc:
            result["llm"] = {"error": f"normalization failed: {exc}"}
        return result

    def _get_llm(self) -> Any:
        """Lazily resolve the LLM adapter."""
        if self._llm is not None:
            return self._llm
        try:
            from core.system.llm_adapter import get_llm
            return get_llm()
        except Exception:  # noqa: BLE001
            return None
