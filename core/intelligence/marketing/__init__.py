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

from typing import Any

from .creative_fatigue import detect_creative_fatigue
from .audience_overlap import detect_audience_overlap
from .retargeting import plan_retargeting_sequence
from .lookalike_tiers import recommend_lookalike_tiers
from .social_proof import audit_social_proof
from .influencer_strategy import plan_influencer_strategy
from .referral_economics import analyze_referral_opportunity
from .email_segments import recommend_email_segments


class MarketingTactics:
    """Real-world marketing intelligence engine."""

    def full_analysis(
        self,
        campaigns: list[dict[str, Any]] | None = None,
        products: list[dict[str, Any]] | None = None,
        customers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run full marketing tactics analysis."""
        result: dict[str, Any] = {}

        if campaigns:
            result["creative_fatigue"] = detect_creative_fatigue(campaigns)
            result["audience_overlap"] = detect_audience_overlap(campaigns)
            result["retargeting_plan"] = plan_retargeting_sequence(campaigns)
            result["lookalike_strategy"] = recommend_lookalike_tiers(campaigns)

        if products:
            result["social_proof_audit"] = audit_social_proof(products)
            result["influencer_strategy"] = plan_influencer_strategy(products)

        if customers:
            result["referral_opportunity"] = analyze_referral_opportunity(customers)
            result["email_segmentation"] = recommend_email_segments(customers)

        return result

    # Delegate methods to standalone functions for backward compatibility
    detect_creative_fatigue = staticmethod(detect_creative_fatigue)
    detect_audience_overlap = staticmethod(detect_audience_overlap)
    plan_retargeting_sequence = staticmethod(plan_retargeting_sequence)
    recommend_lookalike_tiers = staticmethod(recommend_lookalike_tiers)
    audit_social_proof = staticmethod(audit_social_proof)
    plan_influencer_strategy = staticmethod(plan_influencer_strategy)
    analyze_referral_opportunity = staticmethod(analyze_referral_opportunity)
    recommend_email_segments = staticmethod(recommend_email_segments)
